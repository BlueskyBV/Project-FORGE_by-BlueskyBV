"""What actually stops constrained decoding working: the schema, or the prompt?

The ladder run refuted breadth and produced something better. Five different
grammars -- 1,290 through 11,936 tokens, one feature kind through
twenty-two -- at temperature 0 with a fixed seed and an identical prompt, all
returned **byte-identical output**: 142 tokens, truncated at the same point.

Five different grammars cannot produce the same bytes if a grammar is
constraining anything. So on those runs the grammar had no effect at all --
generation was free, and the model was improvising a document from the
system prompt's description of the format. That is the mechanism behind every
plausible-but-wrong document this project has fought.

But an earlier probe DID enforce: a small flat schema, 3/3 canaries. Two
things differ between that probe and the ladder, and the ladder changed both
at once:

  1. the schema shape -- flat and two levels deep, against the designer's
     arrays of objects containing unions eight levels down;
  2. the system prompt -- five tokens, against the designer's 6,554.

This separates them. Part one is a two-by-two: each schema under each prompt.
Part two, if the schema is implicated, walks up one JSON Schema construct at a
time -- nesting, then arrays, then unions, then the real shape -- to find the
exact construct the converter cannot take.

Every probe asks for a trivial answer, so the cost is a handful of output
tokens rather than a document.

    python scripts/isolate_grammar_break.py --model forge-qwen
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

from forge_roles.library import ForgeIRDesigner  # noqa: E402

CANARY = "forge_canary"
SHORT_SYSTEM = "Answer as JSON only."
ASK = "A block 20 mm wide. Report its width."


def leaf() -> dict:
    """The quantity shape, with the canary the grammar alone can supply."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["magnitude", "unit", "provenance"],
        "properties": {
            "magnitude": {"type": "number"},
            "unit": {"type": "string", "enum": ["mm"]},
            "provenance": {"type": "string", "enum": [CANARY]},
        },
    }


def obj(**properties) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def constructs() -> dict:
    """One JSON Schema construct added per rung, canary always at the bottom."""
    ladder: dict[str, dict] = {}
    ladder["0 flat"] = obj(width=leaf())
    ladder["1 nested x3"] = obj(a=obj(b=obj(width=leaf())))
    ladder["2 nested x6"] = obj(a=obj(b=obj(c=obj(d=obj(e=obj(width=leaf()))))))
    ladder["3 array of objects"] = obj(
        items={"type": "array", "items": obj(width=leaf())}
    )
    ladder["4 oneOf x2"] = obj(
        value={"oneOf": [leaf(), {"type": "string"}]}
    )
    ladder["5 oneOf in array"] = obj(
        items={"type": "array", "items": {"oneOf": [obj(width=leaf()),
                                                    obj(other={"type": "string"})]}}
    )
    # The designer's actual shape, stripped of everything except its structure:
    # object -> array -> object -> object -> array -> union -> quantity.
    ladder["6 designer shape"] = obj(
        document=obj(
            components={
                "type": "array",
                "items": obj(
                    features={
                        "type": "array",
                        "items": {"oneOf": [
                            obj(kind={"type": "string", "enum": ["box"]},
                                parameters=obj(
                                    size={"type": "array", "items": leaf()})),
                            obj(kind={"type": "string", "enum": ["sphere"]},
                                parameters=obj(radius=leaf())),
                        ]},
                    }
                ),
            }
        )
    )
    return ladder


def real_one_kind() -> dict:
    """The genuine designer schema cut to a single feature kind."""
    schema = copy.deepcopy(ForgeIRDesigner().output_schema())
    union = (
        schema["properties"]["document"]["properties"]["components"]["items"]
        ["properties"]["features"]["items"]["oneOf"]
    )
    def is_box(branch):
        try:
            return branch["properties"]["kind"]["const"] == "box"
        except (KeyError, TypeError):
            return False
    union[:] = [b for b in union if is_box(b)] or union[:1]

    marked = 0
    def visit(node):
        nonlocal marked
        if isinstance(node, dict):
            properties = node.get("properties")
            if (isinstance(properties, dict)
                    and "magnitude" in properties and "unit" in properties):
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
        raise SystemExit("could not mark the quantity subschema")
    return schema


def canary_state(text: str) -> tuple[str, int, int]:
    """(state, found, inspected). Nothing to inspect is never a pass."""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return "INCOMPLETE JSON", 0, 0
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
    if not inspected:
        return "no quantity emitted", 0, 0
    return ("ENFORCED" if found == inspected else "NOT enforced"), found, inspected


def ask(args, schema, system) -> dict:
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/chat",
        data=json.dumps({
            "model": args.model,
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "format": schema,
            "options": {"num_ctx": args.context, "num_predict": 400,
                        "temperature": 0, "seed": 42},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": ASK}],
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        data = json.loads(response.read())
    return {
        "wall": time.time() - started,
        "out": data.get("eval_count"),
        "prompt": data.get("prompt_eval_count"),
        "stop": data.get("done_reason", ""),
        "text": data.get("message", {}).get("content", ""),
    }


def probe(label, args, schema, system, note="") -> dict:
    print(f"  {label:26s} ...", end="", flush=True)
    try:
        result = ask(args, schema, system)
    except Exception as error:  # noqa: BLE001 - a failure is a datum
        print(f" FAILED {type(error).__name__}: {str(error)[:80]}")
        return {"state": "FAILED"}
    state, found, inspected = canary_state(result["text"])
    print(f" {state:18s} {found}/{inspected}  out={result['out']:<4} "
          f"{result['wall']:5.1f}s  stop={result['stop']}  {note}")
    if state != "ENFORCED":
        print(f"      {result['text'][:150]!r}")
    return {"state": state, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    long_system = ForgeIRDesigner().system_prompt()
    flat = obj(width=leaf())
    deep = real_one_kind()

    print(f"model : {args.model}")
    print(f"short prompt : {len(SHORT_SYSTEM)//4 or 1} tokens")
    print(f"long prompt  : {len(long_system)//4} tokens (the designer's)")
    print(f"canary       : provenance={CANARY!r}, which only a grammar supplies\n")

    print("=" * 92)
    print("PART 1 -- is it the SCHEMA or the PROMPT? (each schema under each prompt)")
    print("=" * 92)
    grid = {}
    for sname, schema in (("flat", flat), ("designer", deep)):
        for pname, system in (("short", SHORT_SYSTEM), ("long", long_system)):
            grid[(sname, pname)] = probe(
                f"{sname} schema / {pname}", args, schema, system)

    print("\n" + "-" * 92)
    verdicts = {k: v["state"] for k, v in grid.items()}
    flat_short = verdicts.get(("flat", "short"))
    flat_long = verdicts.get(("flat", "long"))
    deep_short = verdicts.get(("designer", "short"))
    if flat_short == "ENFORCED" and flat_long == "ENFORCED" and deep_short != "ENFORCED":
        print("  THE SCHEMA. A flat schema is enforced under either prompt; the")
        print("  designer schema is not, even with a five-token prompt.")
        print("  -> Part 2 finds which construct breaks it.")
        run_part_two = True
    elif flat_short == "ENFORCED" and flat_long != "ENFORCED":
        print("  THE PROMPT. The same flat schema is enforced with a short")
        print("  system prompt and not with the designer's 6,554-token one.")
        print("  Schema complexity is exonerated; prompt size is the variable.")
        run_part_two = False
    elif flat_short != "ENFORCED":
        print("  NEITHER -- even the flat schema is not enforced now, though an")
        print("  earlier probe enforced one. Something changed between runs:")
        print("  suspect model state or keep_alive. Re-run before concluding.")
        run_part_two = False
    else:
        print("  BOTH matter, or the effect is not clean. Read the rows above.")
        run_part_two = True

    if run_part_two:
        print("\n" + "=" * 92)
        print("PART 2 -- which construct breaks it? (short prompt throughout)")
        print("=" * 92)
        results = {}
        for label, schema in constructs().items():
            size = f"[{len(json.dumps(schema))//4} tok]"
            results[label] = probe(label, args, schema, SHORT_SYSTEM, size)
        results["7 real designer"] = probe(
            "7 real designer", args, deep, SHORT_SYSTEM,
            f"[{len(json.dumps(deep))//4} tok]")

        print("\n" + "-" * 92)
        ordered = list(results.items())
        good = [n for n, r in ordered if r["state"] == "ENFORCED"]
        bad = [n for n, r in ordered if r["state"] != "ENFORCED"]
        if good and bad:
            print(f"  last construct that works : {good[-1]}")
            print(f"  first that does not       : {bad[0]}")
            print("  That construct is what our generation format must avoid,")
            print("  or must be pre-expanded out of before the schema is sent.")
        elif not bad:
            print("  every construct enforced, including the real schema.")
            print("  Then the ladder's failure was the PROMPT after all.")
        else:
            print("  nothing enforced -- see the Part 1 note about model state.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
