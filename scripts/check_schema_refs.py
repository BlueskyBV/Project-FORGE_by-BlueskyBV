"""Does the way Forge actually talks to this endpoint resolve `$ref`/`$defs`?

Forge's designer schema writes the same quantity union out 35 times, because
nothing collapses it into `$defs`. Collapsing it gives back about 7,300 tokens
on every designer call with no change in meaning -- but only if the endpoint
resolves the references when it turns the schema into a decoding grammar. A
schema that is silently not enforced is worse than a large one that works, so
this asks rather than assumes.

It sends the SAME contract twice, once written out in full and once as `$defs`
plus `$ref`, and compares what comes back.

**It asks through Forge's own provider**, with the flags you design with. The
first version of this script spoke HTTP itself, and got a false answer for it:
the model replied with prose-wrapped JSON instead of a real tool call, the
probe threw that away as unparseable, and the verdict logic then read "0 of 0
canaries" as success. Forge's client has fallbacks for exactly that reply
shape. A probe that reimplements the transport tests a transport nobody runs.

The test turns on a canary: a required field, buried inside the repeated
subschema, whose only permitted value is a word no model would volunteer. If
the grammar is enforced the canary is in every answer, because nothing else
can be emitted; if the reference was dropped, the constrained part goes with
it and the canary almost never appears. That is what separates "the endpoint
enforced my schema" from "the model guessed the shape", which a well-formed
answer on its own cannot tell you.

Run it with the flags from your design command::

    python scripts/check_schema_refs.py --model forge-qwen \
        --structured-mode tools --schema-dialect json_schema --exact-schema

Add `--native` to also test Ollama's own grammar-constrained `/api/chat`,
which Forge does not use today. Roughly forty output tokens per probe.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "packages"))

from forge_models import ModelRequest, user  # noqa: E402
from forge_models.openai_compatible import OpenAICompatibleProvider  # noqa: E402

#: A value the model would never write on its own. Short, so it costs almost
#: nothing to generate, and unmistakable when it appears.
CANARY = "forge_canary"

PROMPT = (
    "A rectangular plate 10 mm wide, 20 mm deep and 30 mm thick. "
    "Report its three dimensions."
)


def quantity() -> dict:
    """One dimensional value -- the subschema Forge repeats 35 times."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["magnitude", "unit", "provenance"],
        "properties": {
            "magnitude": {"type": "number"},
            "unit": {"type": "string", "enum": ["mm"]},
            # The canary, one level down, where the real schema's repeated
            # structure actually lives.
            "provenance": {"type": "string", "enum": [CANARY]},
        },
    }


def inlined() -> dict:
    """The contract with every occurrence written out, as Forge does today."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["width", "depth", "thickness"],
        "properties": {
            "width": quantity(),
            "depth": quantity(),
            "thickness": quantity(),
        },
    }


def referenced() -> dict:
    """The identical contract, collapsed into `$defs` and `$ref`."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["width", "depth", "thickness"],
        "properties": {
            "width": {"$ref": "#/$defs/quantity"},
            "depth": {"$ref": "#/$defs/quantity"},
            "thickness": {"$ref": "#/$defs/quantity"},
        },
        "$defs": {"quantity": quantity()},
    }


def canaries(payload) -> tuple[int, int, str]:
    """How many of the three values carry the canary.

    Returns (found, inspected, problem). `inspected` is zero when there was
    nothing to look at, which is a NO VERDICT and never a pass -- the bug that
    made the first version of this script report success on an empty reply.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return 0, 0, "reply was not JSON"
    if not isinstance(payload, dict) or not payload:
        return 0, 0, "reply was not a JSON object"
    fields = [f for f in ("width", "depth", "thickness") if f in payload]
    if not fields:
        return 0, 0, "reply had none of the required fields"
    found = sum(
        1
        for f in fields
        if isinstance(payload[f], dict) and payload[f].get("provenance") == CANARY
    )
    return found, len(fields), ""


def through_forge(args, schema) -> dict:
    """Exactly the client, mode and dialect your design command uses."""
    provider = OpenAICompatibleProvider(
        model=args.model,
        base_url=args.base_url.rstrip("/") + "/v1",
        structured_mode=args.structured_mode,
        schema_dialect=args.schema_dialect,
        timeout=args.timeout,
        context_window=args.context,
        allow_schema_reduction=not args.exact_schema,
    )
    response = provider.complete(
        ModelRequest(
            system="Answer with the structure you were given.",
            messages=(user(PROMPT),),
            schema=schema,
            schema_name="dimensions",
            schema_description="The plate's three dimensions.",
            max_output_tokens=200,
            temperature=0.0,
            purpose="schema_ref_probe",
        )
    )
    return {
        "payload": response.structured if response.structured else response.text,
        "stop": str(response.stop_reason),
    }


def through_native(args, schema) -> dict:
    """Ollama's own `/api/chat`, where `format` IS the decoding grammar."""
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
                    "num_predict": 200,
                    "temperature": 0,
                },
                "messages": [
                    {"role": "system", "content": "Answer as JSON only."},
                    {"role": "user", "content": PROMPT},
                ],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        data = json.loads(response.read())
    return {
        "payload": data.get("message", {}).get("content", ""),
        "stop": data.get("done_reason", ""),
    }


def probe(label, call, args, schema) -> dict:
    started = time.time()
    try:
        result = call(args, schema)
    except Exception as error:  # noqa: BLE001 - any failure is itself a result
        return {
            "label": label,
            "outcome": "FAILED",
            "detail": f"{type(error).__name__}: {str(error)[:300]}",
        }
    found, inspected, problem = canaries(result["payload"])
    return {
        "label": label,
        "outcome": "ANSWERED",
        "found": found,
        "inspected": inspected,
        "problem": problem,
        "seconds": round(time.time() - started, 1),
        "stop": result["stop"],
        "raw": str(result["payload"])[:160],
    }


def verdict(transport, full, ref) -> None:
    print(f"\n{transport}")
    if full["outcome"] != "ANSWERED":
        print(f"  NO VERDICT: the inlined schema failed outright "
              f"({full['detail']}).")
        return
    if ref["outcome"] != "ANSWERED":
        print(f"  VERDICT: $ref is REJECTED -- {ref['detail']}")
        print("           Keep this schema inlined, or expand the refs before")
        print("           sending. Safe failure: nothing is silently unenforced.")
        return
    # Nothing to inspect proves nothing. This is the case the first version of
    # the script scored as a pass.
    for side, result in (("inlined", full), ("$ref", ref)):
        if result["inspected"] == 0:
            print(f"  NO VERDICT: the {side} probe returned nothing to inspect "
                  f"({result['problem']}).")
            print(f"              stop={result['stop']}  raw={result['raw']!r}")
            return
    if full["found"] < full["inspected"]:
        print(f"  WARNING: the INLINED schema is already not enforced "
              f"({full['found']}/{full['inspected']} canaries).")
        print("           This transport is not constraining generation at all,")
        print("           with or without $ref. That is a bigger finding than")
        print("           the one this script set out to test.")
        return
    if ref["found"] == ref["inspected"]:
        saved = full["seconds"] - ref["seconds"]
        print(f"  VERDICT: $ref IS RESOLVED and enforced "
              f"({ref['found']}/{ref['inspected']} canaries, same as inlined).")
        print(f"           Safe to collapse the designer schema into $defs:")
        print(f"           about 7,300 tokens back per call.")
        if saved > 0:
            print(f"           This probe alone ran {saved:.1f}s faster on the "
                  f"smaller schema.")
    else:
        print(f"  VERDICT: $ref is ACCEPTED BUT NOT ENFORCED "
              f"({ref['found']}/{ref['inspected']} against "
              f"{full['found']}/{full['inspected']} inlined).")
        print("           The dangerous case: the request succeeds and the")
        print("           constraint is silently gone. Do NOT use $defs here.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--structured-mode", default="tools",
                        choices=("json_schema", "tools", "json_object"))
    parser.add_argument("--schema-dialect", default="json_schema",
                        choices=("json_schema", "openapi", "opaque"))
    parser.add_argument("--exact-schema", action="store_true")
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--native", action="store_true",
                        help="also test Ollama's own /api/chat, which Forge "
                             "does not use today")
    args = parser.parse_args()

    print(f"endpoint : {args.base_url}")
    print(f"model    : {args.model}")
    print(f"as Forge : --structured-mode {args.structured_mode} "
          f"--schema-dialect {args.schema_dialect}"
          f"{' --exact-schema' if args.exact_schema else ''}")
    print(f"canary   : every value must carry provenance={CANARY!r}\n")

    transports = [(f"Forge client ({args.structured_mode})", through_forge)]
    if args.native:
        transports.append(("Ollama native /api/chat", through_native))

    outcomes = []
    for label, call in transports:
        for shape, schema in (("inlined", inlined()), ("$ref", referenced())):
            print(f"  running {label:28s} {shape:8s} ...", flush=True)
            result = probe(label, call, args, schema)
            result["shape"] = shape
            outcomes.append(result)
            if result["outcome"] == "ANSWERED":
                print(f"    {result['found']}/{result['inspected']} canaries, "
                      f"{result['seconds']}s, stop={result['stop']}")
            else:
                print(f"    FAILED: {result['detail']}")

    print("\n" + "=" * 64)
    for label, _ in transports:
        pair = [r for r in outcomes if r["label"] == label]
        verdict(label,
                next(r for r in pair if r["shape"] == "inlined"),
                next(r for r in pair if r["shape"] == "$ref"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
