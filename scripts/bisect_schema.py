"""Which property of the real designer schema stops the grammar finishing?

Established so far, and each of these is measured rather than reasoned:

  * The grammar IS applied to the real schema. Under a five-token system
    prompt the model still emits `rationale`, `document`, `name`,
    `components` -- keys it could not have guessed from the prompt.
  * It is the schema, not the prompt: a flat schema is enforced under the
    designer's full 6,554-token prompt.
  * Nesting, arrays and unions are individually fine. A hand-built replica of
    the designer's exact SHAPE -- object, array, object, array, union,
    quantity -- is enforced at 361 tokens.
  * The genuine schema at 1,290 tokens is not. Generation stops around 110-140
    tokens, in the middle of `"components": [{`, reporting a normal stop.

So something the real schema carries, and the replica does not, makes the
converter abandon the grammar partway. Candidates, counted from the real
thing: 144 `description` fields, 184 `additionalProperties: false`, 75 unions,
311 entries across `required`, 22 `const`, and a maximum nesting depth of 22.

Rather than build more replicas and guess, this takes the real schema and
removes one property at a time. A transform that restores the canary names
the cause. If none does alone, it applies them cumulatively until one does,
which brackets it.

Every probe asks for one dimension, so answers are a few dozen tokens.

    python scripts/bisect_schema.py --model forge-qwen
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
SYSTEM = "Answer as JSON only."
ASK = "A block 20 mm wide. Report it."


# ------------------------------------------------------------- transforms


def strip_descriptions(schema):
    """144 of them. Prose the grammar must carry but never constrains."""
    if isinstance(schema, dict):
        return {k: strip_descriptions(v) for k, v in schema.items()
                if k != "description"}
    if isinstance(schema, list):
        return [strip_descriptions(v) for v in schema]
    return schema


def const_to_enum(schema):
    """22 of them. Some converters treat `const` as a separate rule kind."""
    if isinstance(schema, dict):
        node = {k: const_to_enum(v) for k, v in schema.items() if k != "const"}
        if "const" in schema:
            node["enum"] = [schema["const"]]
        return node
    if isinstance(schema, list):
        return [const_to_enum(v) for v in schema]
    return schema


def open_objects(schema):
    """184 `additionalProperties: false`. Each one forbids every other key,
    which a converter must express as a closed alternation."""
    if isinstance(schema, dict):
        return {k: open_objects(v) for k, v in schema.items()
                if k != "additionalProperties"}
    if isinstance(schema, list):
        return [open_objects(v) for v in schema]
    return schema


def first_branch_only(schema):
    """Collapse every union to its first branch, except the feature union
    which is already cut to one kind. 75 unions become none."""
    if isinstance(schema, dict):
        if isinstance(schema.get("oneOf"), list) and schema["oneOf"]:
            return first_branch_only(schema["oneOf"][0])
        return {k: first_branch_only(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [first_branch_only(v) for v in schema]
    return schema


def drop_required(schema):
    """311 required entries. Keeps the shape, removes the obligations."""
    if isinstance(schema, dict):
        return {k: drop_required(v) for k, v in schema.items() if k != "required"}
    if isinstance(schema, list):
        return [drop_required(v) for v in schema]
    return schema


def drop_component_extras(schema):
    """Keep only `features` inside a component -- no interfaces, no
    component-level parameters -- which cuts both breadth and depth."""
    schema = copy.deepcopy(schema)
    try:
        component = (schema["properties"]["document"]["properties"]
                     ["components"]["items"])
        keep = {k: v for k, v in component["properties"].items()
                if k in ("id", "features")}
        component["properties"] = keep
        if isinstance(component.get("required"), list):
            component["required"] = [r for r in component["required"] if r in keep]
    except (KeyError, TypeError):
        pass
    return schema


def unwrap(schema):
    """Drop the rationale/document wrapper; ask for the document alone."""
    try:
        return copy.deepcopy(schema["properties"]["document"])
    except (KeyError, TypeError):
        return schema


TRANSFORMS = {
    "strip descriptions": strip_descriptions,
    "const -> enum": const_to_enum,
    "allow extra props": open_objects,
    "collapse all unions": first_branch_only,
    "drop required": drop_required,
    "features only": drop_component_extras,
    "no wrapper": unwrap,
}


# ------------------------------------------------------------------ harness


def real_schema() -> dict:
    """The designer schema, one feature kind, canary on every quantity."""
    schema = copy.deepcopy(ForgeIRDesigner().output_schema())
    union = (schema["properties"]["document"]["properties"]["components"]
             ["items"]["properties"]["features"]["items"]["oneOf"])

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


def state_of(text: str) -> tuple[str, int, int]:
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return "INCOMPLETE", 0, 0
    found = seen = 0

    def visit(node):
        nonlocal found, seen
        if isinstance(node, dict):
            if "magnitude" in node and "unit" in node:
                seen += 1
                if node.get("provenance") == CANARY:
                    found += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    if not seen:
        return "no quantity", 0, 0
    return ("ENFORCED" if found == seen else "NOT enforced"), found, seen


def probe(label, args, schema) -> str:
    size = len(json.dumps(schema)) // 4
    print(f"  {label:24s} [{size:5d} tok] ...", end="", flush=True)
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/chat",
        data=json.dumps({
            "model": args.model, "stream": False, "think": False,
            "keep_alive": "10m", "format": schema,
            "options": {"num_ctx": args.context, "num_predict": 500,
                        "temperature": 0, "seed": 42},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": ASK}],
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            data = json.loads(response.read())
    except Exception as error:  # noqa: BLE001
        print(f" FAILED {type(error).__name__}: {str(error)[:70]}")
        return "FAILED"
    text = data.get("message", {}).get("content", "")
    state, found, seen = state_of(text)
    print(f" {state:14s} {found}/{seen}  out={data.get('eval_count'):<4}"
          f" {time.time()-started:5.1f}s")
    if state != "ENFORCED":
        print(f"      {text[:130]!r}")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--context", type=int, default=32768)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    base = real_schema()
    print(f"model  : {args.model}")
    print(f"canary : provenance={CANARY!r}\n")

    print("=" * 84)
    print("BASELINE")
    print("=" * 84)
    if probe("real schema, 1 kind", args, base) == "ENFORCED":
        print("\n  The baseline already enforces. Nothing to bisect -- the earlier")
        print("  failure was not reproducible. Re-run the isolation script.\n")
        return 0

    print("\n" + "=" * 84)
    print("ONE TRANSFORM AT A TIME -- a pass names the cause")
    print("=" * 84)
    winners = []
    for label, transform in TRANSFORMS.items():
        if probe(label, args, transform(copy.deepcopy(base))) == "ENFORCED":
            winners.append(label)

    if not winners:
        print("\n" + "=" * 84)
        print("CUMULATIVE -- no single removal was enough, so stack them")
        print("=" * 84)
        schema = copy.deepcopy(base)
        applied = []
        for label, transform in TRANSFORMS.items():
            schema = transform(schema)
            applied.append(label)
            if probe(f"+ {label}", args, schema) == "ENFORCED":
                print(f"\n  RESTORED once these were removed: {', '.join(applied)}")
                print("  The last one added is the likeliest cause; the set is the")
                print("  bracket. Narrow it by re-running with that one alone.")
                break
        else:
            print("\n  Nothing restored it, even with everything removed. That points")
            print("  at sheer schema SIZE or depth rather than any one construct.")
            print("  Next: shrink the real schema by halves and find the threshold.")
    else:
        print("\n" + "=" * 84)
        print("CAUSE FOUND")
        print("=" * 84)
        for label in winners:
            print(f"  removing `{label}` restores enforcement")
        print("\n  That is what the generation format has to avoid, or what we")
        print("  strip from the schema on the way to the endpoint -- the stored")
        print("  ForgeIR contract does not have to change at all.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
