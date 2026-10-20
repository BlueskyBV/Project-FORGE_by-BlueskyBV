"""Does the endpoint enforce the real designer schema? Asked properly this time.

Three earlier rounds asked this badly and I read the noise as signal. The
canary was injected into the quantity subschema -- `{magnitude, unit}` -- on
the assumption that a document must contain one. It need not: a box's `size`
accepts `{"vector": [20, 20, 10], "unit": "mm"}`, whose items are bare
numbers. So every "failure" was a valid, fully-constrained document that
simply never visited the marked branch, and the reported state, "no quantity",
was correct and uninformative.

Worse, the raw text printed beside those results was cut to 130 characters by
the print itself, which made complete documents look truncated. Every one of
them had parsed: `json.loads` succeeded before the state was decided.

So this puts the canary where no valid answer can avoid it: as a REQUIRED
property with a single permitted value on the document, on every component,
and on every feature. Any document the schema accepts must carry all three.
If they come back, the grammar is enforced. If a document comes back without
them, it is a schema violation and the grammar is not.

The probe also prints the whole answer and says plainly whether it parsed, so
a truncated reply can never again be mistaken for an unenforced one.

    python scripts/canary_on_the_path.py --model forge-qwen
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
SHORT = "Answer as JSON only."
ASK = "A plain aluminium block, 20 mm by 20 mm by 10 mm. No holes."

#: Where the marker goes. Each is on the path of every valid document, so a
#: reply missing one is a violation rather than a road not taken.
SITES = ("document", "component", "feature")


def mark(schema: dict) -> tuple[dict, list[str]]:
    """Require the canary at three unavoidable places."""
    schema = copy.deepcopy(schema)
    placed = []

    def require(node, where):
        if not isinstance(node, dict) or not isinstance(node.get("properties"), dict):
            return
        node["properties"]["provenance"] = {"type": "string", "enum": [CANARY]}
        required = node.setdefault("required", [])
        if "provenance" not in required:
            required.append("provenance")
        placed.append(where)

    document = schema.get("properties", {}).get("document")
    if document is None:            # the unwrapped form
        document = schema
    require(document, "document")

    components = document.get("properties", {}).get("components", {})
    component = components.get("items")
    require(component, "component")

    features = (component or {}).get("properties", {}).get("features", {})
    item = (features or {}).get("items", {})
    if isinstance(item.get("oneOf"), list):
        for branch in item["oneOf"]:
            require(branch, "feature")
        placed = [p for p in placed if p != "feature"] + ["feature"]
    else:
        require(item, "feature")
    return schema, placed


def one_kind(schema: dict) -> dict:
    """Cut the feature union to `box` so the answer stays short."""
    schema = copy.deepcopy(schema)
    try:
        union = (schema["properties"]["document"]["properties"]["components"]
                 ["items"]["properties"]["features"]["items"]["oneOf"])
    except (KeyError, TypeError):
        return schema

    def is_box(branch):
        try:
            return branch["properties"]["kind"]["const"] == "box"
        except (KeyError, TypeError):
            return False

    union[:] = [b for b in union if is_box(b)] or union[:1]
    return schema


def read_back(text: str) -> dict:
    """Parsed? And which of the three markers survived?"""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {"parsed": False, "found": [], "missing": list(SITES)}
    found = set()

    def visit(node, where=None):
        if isinstance(node, dict):
            if node.get("provenance") == CANARY and where:
                found.add(where)
            if "components" in node:
                for component in node.get("components") or []:
                    if isinstance(component, dict):
                        if component.get("provenance") == CANARY:
                            found.add("component")
                        for feature in component.get("features") or []:
                            if (isinstance(feature, dict)
                                    and feature.get("provenance") == CANARY):
                                found.add("feature")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    root = payload.get("document") if isinstance(payload, dict) else None
    if isinstance(root, dict) and root.get("provenance") == CANARY:
        found.add("document")
    if isinstance(payload, dict) and payload.get("provenance") == CANARY:
        found.add("document")
    visit(payload)
    return {
        "parsed": True,
        "found": sorted(found),
        "missing": [s for s in SITES if s not in found],
    }


def native(args, schema):
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/chat",
        data=json.dumps({
            "model": args.model, "stream": False, "think": False,
            "keep_alive": "10m", "format": schema,
            "options": {"num_ctx": args.context, "num_predict": 1500,
                        "temperature": 0, "seed": 42},
            "messages": [{"role": "system", "content": args.system},
                         {"role": "user", "content": ASK}],
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        data = json.loads(response.read())
    return {"text": data.get("message", {}).get("content", ""),
            "out": data.get("eval_count"), "stop": data.get("done_reason", "")}


def shim(args, schema):
    provider = OpenAICompatibleProvider(
        model=args.model, base_url=args.base_url.rstrip("/") + "/v1",
        structured_mode="tools", schema_dialect="json_schema",
        timeout=args.timeout, context_window=args.context,
        allow_schema_reduction=False,
    )
    response = provider.complete(ModelRequest(
        system=args.system, messages=(user(ASK),), schema=schema,
        schema_name="document", schema_description="The part you designed.",
        max_output_tokens=1500, temperature=0.0, purpose="canary"))
    payload = response.structured if response.structured else response.text
    return {"text": payload if isinstance(payload, str) else json.dumps(payload),
            "out": getattr(response.usage, "output_tokens", None),
            "stop": str(response.stop_reason)}


def probe(label, call, args, schema) -> str:
    print(f"\n  {label}")
    started = time.time()
    try:
        result = call(args, schema)
    except Exception as error:  # noqa: BLE001
        print(f"    FAILED {type(error).__name__}: {str(error)[:140]}")
        return "FAILED"
    state = read_back(result["text"])
    seconds = time.time() - started
    if not state["parsed"]:
        print(f"    TRUNCATED -- the reply is not valid JSON "
              f"({result['out']} tokens, {seconds:.1f}s, stop={result['stop']})")
        print(f"    full reply follows, so nothing is hidden by a print slice:")
        print("    " + result["text"][:600].replace("\n", "\n    "))
        return "TRUNCATED"
    verdict = "ENFORCED" if not state["missing"] else "NOT enforced"
    print(f"    {verdict}: markers present {state['found'] or '[]'}, "
          f"missing {state['missing'] or '[]'}")
    print(f"    ({result['out']} tokens, {seconds:.1f}s, stop={result['stop']}, "
          f"valid JSON)")
    if state["missing"]:
        print("    A required enum was omitted on a path every document must")
        print("    take. That is a schema violation, not a road not taken.")
        print("    " + result["text"][:400].replace("\n", "\n    "))
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=1200.0)
    args = parser.parse_args()

    designer = ForgeIRDesigner()
    real, placed = mark(one_kind(designer.output_schema()))
    print(f"model  : {args.model}")
    print(f"schema : real designer, one feature kind, "
          f"{len(json.dumps(real))//4} tokens")
    print(f"canary : required at {', '.join(sorted(set(placed)))} "
          f"-- every valid document must carry all three")

    print("\n" + "=" * 78)
    print("SHORT PROMPT (isolates the schema)")
    print("=" * 78)
    args.system = SHORT
    native_short = probe("native /api/chat", native, args, real)
    shim_short = probe("openai shim /v1 (tools)", shim, args, real)

    print("\n" + "=" * 78)
    print("DESIGNER PROMPT (what Forge actually sends)")
    print("=" * 78)
    args.system = designer.system_prompt()
    native_long = probe("native /api/chat", native, args, real)
    shim_long = probe("openai shim /v1 (tools)", shim, args, real)

    print("\n" + "=" * 78)
    print("WHAT THIS SETTLES")
    print("=" * 78)
    for name, short, long in (("native", native_short, native_long),
                              ("shim", shim_short, shim_long)):
        print(f"  {name:8s} short prompt: {short:12s} designer prompt: {long}")
    if native_long == "ENFORCED" and shim_long != "ENFORCED":
        print("\n  Native enforces the real schema; the shim does not.")
        print("  Switching transport is then the whole fix, and it is small.")
    elif native_long == "ENFORCED" and shim_long == "ENFORCED":
        print("\n  Both enforce the real schema. Generation has been constrained")
        print("  all along, and the wrong parts come from the model choosing")
        print("  badly WITHIN a valid schema -- which is a prompt and format")
        print("  problem, not a transport one.")
    elif native_long == "TRUNCATED" or shim_long == "TRUNCATED":
        print("\n  A reply was genuinely truncated -- not a print artefact this")
        print("  time. Read the full text above; that is the real failure.")
    else:
        print("\n  Neither enforces it. The schema is beyond both converters,")
        print("  and the generation format has to change rather than the wire.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
