"""Where does constrained decoding give up on Forge's schema?

The previous run produced the most important result of this project, and it
needs confirming before anything is built on it.

  * A three-field toy schema was ENFORCED: every value carried a canary that
    only the grammar could have put there.
  * The real designer schema was NOT. Through the OpenAI shim the model
    emitted three quantities and ignored a required enum on all three
    (0/3). Through Ollama's native endpoint it stopped after 142 tokens in
    the middle of an object, reporting a normal stop -- which a grammar
    requiring a complete document cannot permit.

If that holds, generation has been effectively UNCONSTRAINED on every real
run: the converter meets a schema it cannot turn into a grammar, quietly
falls back to free decoding, and the model improvises JSON that looks about
right. It would explain years of this week -- documents that are structurally
plausible and semantically wrong, in ways our validators then have to catch
one at a time.

The suspect is breadth. The features array is a `oneOf` over all 22 feature
kinds, and a wide union of deep object branches is exactly what grammar
converters choke on. So this walks a ladder -- 1, 3, 6, 12, 22 branches --
and finds the rung where the canary stops appearing. That number is the
budget every later design decision has to fit inside.

Deliberately the prompt is IDENTICAL for every probe. On the native endpoint
the schema is compiled to a grammar and never enters the prompt at all (the
last run reported 7177 prompt tokens for three schemas of wildly different
size), so holding the prompt constant costs nothing and lets the prompt cache
make each probe cheap. Only the schema varies, which is the variable under
test.

    python scripts/find_enforcement_limit.py --model forge-qwen

About twenty minutes. `--native-only` halves it.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packages"))

from forge_models import ModelRequest, user  # noqa: E402
from forge_models.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from forge_roles.library import ForgeIRDesigner  # noqa: E402

CANARY = "forge_canary"

#: The simplest part that is still a real document. The question is what the
#: SCHEMA costs, never what the part costs.
BRIEF = "A plain aluminium block, 20 mm by 20 mm by 10 mm. No holes."


def feature_union(schema: dict) -> list | None:
    """The `oneOf` over feature kinds, the widest union in the document."""
    try:
        return (
            schema["properties"]["document"]["properties"]["components"]["items"]
            ["properties"]["features"]["items"]["oneOf"]
        )
    except (KeyError, TypeError):
        return None


def narrowed(schema: dict, branches: int) -> dict:
    """The same schema with the feature union cut to `branches` kinds.

    `box` is kept first whatever the width, so every rung can still express
    the part being asked for. A rung that cannot build the block would fail
    for the wrong reason.
    """
    schema = copy.deepcopy(schema)
    union = feature_union(schema)
    if union is None:
        raise SystemExit("could not locate the feature union")
    def is_box(branch):
        try:
            return branch["properties"]["kind"]["const"] == "box"
        except (KeyError, TypeError):
            return False
    box = [b for b in union if is_box(b)]
    rest = [b for b in union if not is_box(b)]
    union[:] = (box + rest)[:branches]
    return schema


def with_canary(schema: dict) -> dict:
    """Require the canary on every quantity-shaped object."""
    schema = copy.deepcopy(schema)
    marked = 0

    def visit(node):
        nonlocal marked
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
                marked += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    if not marked:
        raise SystemExit("could not find the quantity subschema to mark")
    return schema


def inspect(payload) -> dict:
    """Canary count, and whether the answer was even a complete document.

    Zero inspected is never a pass. The distinction between "complete JSON
    with no canaries" and "JSON that stops mid-object" matters: the first is
    an unenforced grammar, the second is a grammar that was abandoned partway.
    """
    complete = True
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            complete = False
            payload = None
    found = inspected = 0
    if payload is not None:
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
    return {"found": found, "inspected": inspected, "complete_json": complete}


def native(args, schema):
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/chat",
        data=json.dumps(
            {
                "model": args.model,
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "format": schema,
                "options": {
                    "num_ctx": args.context,
                    "num_predict": 1200,
                    "temperature": 0,
                    "seed": 42,
                },
                "messages": [
                    {"role": "system", "content": args.system},
                    {"role": "user", "content": BRIEF},
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
        "out": data.get("eval_count"),
        "prompt_tokens": data.get("prompt_eval_count"),
        "stop": data.get("done_reason", ""),
        "payload": data.get("message", {}).get("content", ""),
    }


def shim(args, schema, dialect="json_schema"):
    provider = OpenAICompatibleProvider(
        model=args.model,
        base_url=args.base_url.rstrip("/") + "/v1",
        structured_mode="tools",
        schema_dialect=dialect,
        timeout=args.timeout,
        context_window=args.context,
        allow_schema_reduction=(dialect != "json_schema"),
    )
    started = time.time()
    response = provider.complete(
        ModelRequest(
            system=args.system,
            messages=(user(BRIEF),),
            schema=schema,
            schema_name="document",
            schema_description="The part you designed.",
            # Generous: a 1-token cap is read as truncation and raises, which
            # is what wasted the previous run's whole Phase A.
            max_output_tokens=1200,
            temperature=0.0,
            purpose="enforcement_ladder",
        )
    )
    return {
        "wall": time.time() - started,
        "out": getattr(response.usage, "output_tokens", None),
        "prompt_tokens": getattr(response.usage, "input_tokens", None),
        "stop": str(response.stop_reason),
        "payload": response.structured or response.text,
    }


def run(label, call, args, schema, size_note) -> dict:
    print(f"  {label:34s} ...", end="", flush=True)
    try:
        result = call(args, schema)
    except Exception as error:  # noqa: BLE001 - a failure is itself a datum
        print(f" FAILED: {type(error).__name__}: {str(error)[:90]}")
        return {"label": label, "failed": True}
    verdict = inspect(result["payload"])
    mark = "ENFORCED" if verdict["inspected"] and verdict["found"] == verdict["inspected"] else (
        "no canaries" if verdict["inspected"] else
        ("INCOMPLETE JSON" if not verdict["complete_json"] else "nothing to inspect")
    )
    print(f" {verdict['found']}/{verdict['inspected']:<3d} {mark:16s} "
          f"{result['wall']:6.1f}s  out={result['out']}  "
          f"prompt={result['prompt_tokens']}  stop={result['stop']}  [{size_note}]")
    if not verdict["complete_json"]:
        print(f"      raw tail: {str(result['payload'])[-110:]!r}")
    return {"label": label, "failed": False, **verdict, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--rungs", default="1,3,6,12,22")
    args = parser.parse_args()

    designer = ForgeIRDesigner()
    args.system = designer.system_prompt()
    base = designer.output_schema()
    width = len(feature_union(base) or [])
    rungs = [int(r) for r in args.rungs.split(",") if int(r) <= width]

    print(f"model   : {args.model}")
    print(f"system  : {len(args.system)//4} tokens (identical for every probe,")
    print(f"          so the prompt cache makes each rung cheap)")
    print(f"union   : {width} feature kinds in the full schema")
    print(f"canary  : every quantity must carry provenance={CANARY!r}\n")

    print("=" * 96)
    print("NATIVE /api/chat  -- schema becomes a decoding grammar, never enters the prompt")
    print("=" * 96)
    native_results = []
    for rung in rungs:
        schema = with_canary(narrowed(base, rung))
        size = f"{len(json.dumps(schema))//4} tok schema"
        native_results.append(run(f"{rung:2d} feature kinds", native, args, schema, size))

    shim_results = []
    if not args.native_only:
        print("\n" + "=" * 96)
        print("OPENAI SHIM /v1 (tools) -- schema rides IN the prompt, so each rung costs a cache miss")
        print("=" * 96)
        for rung in (rungs[0], rungs[-1]):
            schema = with_canary(narrowed(base, rung))
            size = f"{len(json.dumps(schema))//4} tok schema"
            shim_results.append(
                run(f"{rung:2d} feature kinds", shim, args, schema, size))
        print("\n  and the same full schema through the `openapi` dialect, which")
        print("  collapses unions -- if breadth is the problem, this may restore it:")
        schema = with_canary(narrowed(base, rungs[-1]))
        shim_results.append(
            run("full, openapi dialect",
                lambda a, s: shim(a, s, dialect="openapi"), args, schema, "reduced"))

    print("\n" + "=" * 96)
    print("WHERE IT BREAKS")
    print("=" * 96)
    good = [r for r in native_results
            if not r["failed"] and r["inspected"] and r["found"] == r["inspected"]]
    bad = [r for r in native_results
           if not r["failed"] and not (r["inspected"] and r["found"] == r["inspected"])]
    if good and bad:
        print(f"\n  native: enforced up to {good[-1]['label'].strip()}, "
              f"lost by {bad[0]['label'].strip()}.")
        print(f"  That is the budget. Any generation format we design has to fit")
        print(f"  under it, or the grammar is decoration and the model free-runs.")
    elif good and not bad:
        print("\n  native: enforced at EVERY rung, including the full schema.")
        print("  The earlier failure was then not breadth -- re-read the raw tails")
        print("  above; most likely an output cap, not a converter limit.")
    elif bad and not good:
        print("\n  native: enforced at NO rung, not even the narrowest.")
        print("  That points at the canary injection or the endpoint itself")
        print("  rather than at schema complexity. Check the raw tails.")
    for result in shim_results:
        if result["failed"]:
            continue
        state = ("ENFORCED" if result["inspected"] and result["found"] == result["inspected"]
                 else "NOT enforced")
        print(f"  shim {result['label'].strip():24s}: {state}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
