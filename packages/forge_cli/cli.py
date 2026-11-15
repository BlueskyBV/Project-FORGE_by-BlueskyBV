"""``forge`` - command line entry point.

Subcommands:

``design``    a sentence in, a verified ForgeIR document and its evidence out
``spec``      a brief in, its part spec drafted, settled with you and confirmed (V2)
``build``     a confirmed spec built, judged on every view, and its files released (V2)
``eval-spec`` draft every brief of a locked answer-key set, and grade the drafts (V2)
``eval-corpus`` draft every recorded brief, and build each determinate draft (V2)
``eval-false-passes`` draft V1's 27 false passes under --auto, build them, judge them by their keys (V2)
``doctor``    check the exact kernel works here: its pins, a probe part, STEP, STL and 3MF (V2)
``verify``    compile a ForgeIR document, measure it, run gates, print evidence
``export``    write a mesh (STL/OBJ) from a document
``inspect``   show the feature graph, parameters and published geometry
``sweep``     vary a parameter and report how the incremental compiler behaves
``accept``    approve the assumptions that are holding a design back
``capability`` print the truthful capability matrix

The exit code follows the release verdict: 0 for ``PASS``, 1 for ``FAIL``, 2 for
anything undecided (``BLOCKED``, ``INCONCLUSIVE``, ``NOT_TESTED``). That makes
the distinction usable in CI, where "we could not check" must not be scripted as
success any more than it is reported as success. ``design`` adds a fourth: 3
means the run stopped to ask a question rather than invent an answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from forge_evidence import Status
from forge_geom import (
    PRINT_CELL,
    extract_manifold_surface,
    extract_print_surface,
    extract_surface,
    write_obj,
    write_stl,
)
from forge_ir import Document
from forge_kernel import Compiler, backend_capabilities
from forge_pipeline import LoadCase, verify_component
from forge_units import Q, Quantity

from .build import add_build_parser
from .design import EXIT_QUESTIONS, add_design_parser
from .doctor import add_doctor_parser
from .eval_corpus import add_eval_corpus_parsers
from .eval_spec import add_eval_spec_parser
from .spec import add_spec_parser

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_UNDECIDED = 2


def _load(path: str) -> Document:
    return Document.from_json(Path(path).read_text(encoding="utf-8"))


def _pick_component(document: Document, identifier: str | None):
    if identifier:
        return document.component(identifier)
    if len(document.components) != 1:
        raise SystemExit(
            "this document has several components; name one with --component: "
            + ", ".join(c.identifier for c in document.components)
        )
    return document.components[0]


def _parse_overrides(values: list[str]) -> dict[str, Quantity]:
    overrides: dict[str, Quantity] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(
                f"override '{item}' must be written name=value, e.g. "
                "ear_thickness=8mm"
            )
        name, _, text = item.partition("=")
        overrides[name.strip()] = Quantity.parse(text.strip())
    return overrides


def _exit_code(status: Status) -> int:
    if status is Status.PASS:
        return EXIT_PASS
    if status is Status.FAIL:
        return EXIT_FAIL
    return EXIT_UNDECIDED


# ----------------------------------------------------------------------
def command_verify(args: argparse.Namespace) -> int:
    document = _load(args.document)
    component = _pick_component(document, args.component)
    load_case = None
    if args.load and args.arm:
        load_case = LoadCase(
            "cli_load",
            Quantity.parse(args.load),
            Quantity.parse(args.arm),
            assumption_id=args.load_assumption or "",
        )
    report = verify_component(
        document,
        component,
        overrides=_parse_overrides(args.set or []),
        load_case=load_case,
        measurement_depth=args.depth,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(report.render())
        print()
        print("Measurements")
        for key, value in report.measurements.items():
            print(f"  {key:24}: {value}")
        print(f"  {'elapsed':24}: {report.duration_seconds:.2f} s")
    return _exit_code(report.overall_status)


def command_export(args: argparse.Namespace) -> int:
    document = _load(args.document)
    component = _pick_component(document, args.component)
    part = Compiler().compile_component(
        component, overrides=_parse_overrides(args.set or [])
    )
    mesh = None
    if args.resolution is None:
        # Meshed for printing (see forge_geom.mesh.PRINT_CELL); the coarser
        # surface only when no fine grid closes.
        mesh = extract_print_surface(part.solid, cell=args.cell)
    if mesh is None:
        mesh = extract_manifold_surface(part.solid,
                                        resolution=args.resolution or 140)
    target = Path(args.output)
    if target.suffix.lower() == ".stl":
        write_stl(mesh, target, name=component.identifier)
    elif target.suffix.lower() == ".obj":
        write_obj(mesh, target, name=component.identifier)
    else:
        raise SystemExit("output must end in .stl or .obj")
    watertight, stats = mesh.is_watertight()
    print(f"wrote {target}  ({mesh.face_count} faces, watertight={watertight})")
    if not watertight:
        print(f"  WARNING: mesh is not closed: {stats}")
        return EXIT_UNDECIDED
    return EXIT_PASS


def command_inspect(args: argparse.Namespace) -> int:
    document = _load(args.document)
    component = _pick_component(document, args.component)
    part = Compiler().compile_component(component)

    print(f"Document   : {document.name}  (revision {document.revision})")
    print(f"Component  : {component.identifier} - {component.name}")
    print(f"Material   : {component.material or '(none declared)'}")
    print(f"Part hash  : {part.part_hash}")
    print()
    print("Parameters (in resolution order)")
    for identifier in part.resolution.order:
        resolved = part.resolution.parameters[identifier]
        kind = "free " if resolved.is_free else "derived"
        source = f"  = {resolved.source_expression}" if resolved.source_expression else ""
        print(f"  {kind} {identifier:20} {str(resolved.value):>22}{source}")
    print()
    print("Feature graph (dependency order)")
    for trace in part.traces:
        feature = component.features[trace.feature_id]
        inputs = ", ".join(feature.inputs) or "-"
        print(f"  {trace.feature_id:18} {trace.kind:18} inputs: {inputs}")
    print()
    print("Published geometry")
    for entity in part.geometry_map:
        note = f"  {entity.note}" if entity.note else ""
        print(
            f"  {entity.name:26} {entity.entity_type:18} "
            f"{entity.status.value:8} {entity.token[:12]}{note}"
        )
    return EXIT_PASS


def command_sweep(args: argparse.Namespace) -> int:
    """Vary one parameter and report what the incremental compiler did.

    Useful for seeing the cache behaviour an optimisation campaign would get.
    """
    document = _load(args.document)
    component = _pick_component(document, args.component)
    compiler = Compiler()
    unit = Quantity.parse(args.start).unit
    start = Quantity.parse(args.start).to(unit).magnitude.midpoint
    stop = Quantity.parse(args.stop).to(unit).magnitude.midpoint
    steps = max(args.steps, 2)

    print(f"{'value':>12}  {'built':>6} {'reused':>7}  {'ms':>7}  part hash")
    total_built = 0
    for index in range(steps):
        value = start + (stop - start) * index / (steps - 1)
        part = compiler.compile_component(
            component, overrides={args.parameter: Q(value, unit)}
        )
        total_built += part.features_built
        print(
            f"{value:>9.3f} {unit.symbol:<2}  {part.features_built:>6} "
            f"{part.features_reused:>7}  {part.duration_seconds * 1000:>7.1f}  "
            f"{part.part_hash[:16]}"
        )
    statistics = compiler.cache_statistics
    full_rebuild = steps * len(component.features)
    print()
    print(
        f"features built {total_built} of {full_rebuild} a full rebuild would "
        f"need ({100 * (1 - total_built / full_rebuild):.0f}% avoided)"
    )
    print(f"cache: {statistics.as_dict()}")
    return EXIT_PASS


def _render_assumption(assumption: Any) -> list[str]:
    lines = [f"  {assumption.identifier}  [risk {assumption.risk}]"]
    lines.append(f"      {assumption.statement}")
    if assumption.value is not None:
        lines.append(f"      value: {assumption.value}")
    if assumption.rationale:
        lines.append(f"      why:   {assumption.rationale}")
    if assumption.consequence_if_wrong:
        lines.append(f"      if wrong: {assumption.consequence_if_wrong}")
    return lines


def command_accept(args: argparse.Namespace) -> int:
    """Record that a person accepted an assumption. The only exit from BLOCKED.

    ``BLOCKED`` is not a failure and not a pass: the geometry is fine and the
    design rests on a number nobody agreed to. Until now nothing in the tool
    could clear it, which made the verdict a dead end -- and a verdict with no
    exit teaches people to ignore it, which is exactly what it exists to
    prevent.

    Acceptance is a human act, so it is a separate command rather than a flag
    on ``design``: you read what you are accepting and what happens if it is
    wrong, then say so. It is written into the document, which is what a later
    reader -- or a later you -- sees when asking on whose authority a 500 N
    load became a fact.
    """
    path = Path(args.document)
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = Document.from_json(json.dumps(payload))  # validate before editing

    blocking = document.unapproved_blocking_assumptions()
    if not blocking:
        print("Nothing is waiting for approval in this document.")
        return EXIT_PASS

    if not args.all and not args.assumption:
        print(f"{len(blocking)} assumption(s) are holding back this design:")
        print()
        for assumption in blocking:
            print("\n".join(_render_assumption(assumption)))
            print()
        print("Accept them with:")
        print(f"  forge accept {args.document} --assumption {blocking[0].identifier}")
        print(f"  forge accept {args.document} --all")
        return EXIT_UNDECIDED

    wanted = {a.identifier for a in blocking} if args.all else set(args.assumption)
    unknown = sorted(wanted - {a.identifier for a in document.assumptions})
    if unknown:
        raise SystemExit(
            "no such assumption: "
            + ", ".join(unknown)
            + ". This document has: "
            + ", ".join(a.identifier for a in document.assumptions)
        )

    accepted = [a for a in blocking if a.identifier in wanted]
    if not accepted:
        print(
            "Those assumptions are not the ones holding the design back; "
            "nothing changed."
        )
        return EXIT_PASS

    for entry in payload.get("assumptions") or []:
        if entry.get("id") in wanted:
            entry["approved"] = True
    # The document is not the one it was: a reader who accepted revision 3 did
    # not accept revision 4, and the number is how they tell.
    payload["revision"] = int(payload.get("revision", 1)) + 1

    updated = json.dumps(payload, indent=2)
    Document.from_json(updated)  # the edit must still be a valid document
    target = Path(args.out) if args.out else path
    target.write_text(updated + "\n", encoding="utf-8")

    print(f"Accepted {len(accepted)} assumption(s), on your authority:")
    for assumption in accepted:
        print("\n".join(_render_assumption(assumption)))
    print()
    print(f"Written to {target} as revision {payload['revision']}.")
    remaining = Document.from_json(updated).unapproved_blocking_assumptions()
    if remaining:
        print(
            f"{len(remaining)} still waiting: "
            + ", ".join(a.identifier for a in remaining)
        )
        return EXIT_UNDECIDED
    print("Nothing is blocking release now. Re-run `forge verify` to confirm.")
    return EXIT_PASS


def command_capability(args: argparse.Namespace) -> int:
    print(json.dumps(backend_capabilities(), indent=2))
    return EXIT_PASS


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge - evidence-driven parametric design",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("document", help="path to a ForgeIR JSON document")
        sub.add_argument("--component", help="component id, if the document has several")
        sub.add_argument(
            "--set",
            action="append",
            metavar="NAME=VALUE",
            help="override a free parameter, e.g. --set ear_thickness=8mm",
        )

    add_design_parser(subparsers)
    add_spec_parser(subparsers)
    add_build_parser(subparsers)
    add_eval_spec_parser(subparsers)
    add_eval_corpus_parsers(subparsers)
    add_doctor_parser(subparsers)

    verify = subparsers.add_parser("verify", help="compile, measure and gate")
    add_common(verify)
    verify.add_argument("--load", help="applied force, e.g. 500N")
    verify.add_argument("--arm", help="lever arm for the load, e.g. 35mm")
    verify.add_argument("--load-assumption", help="assumption id the load came from")
    verify.add_argument("--depth", type=int, default=9, help="octree refinement depth")
    verify.add_argument("--json", action="store_true", help="emit the full report as JSON")
    verify.set_defaults(handler=command_verify)

    export = subparsers.add_parser("export", help="write a mesh")
    add_common(export)
    export.add_argument("-o", "--output", required=True, help="path ending in .stl or .obj")
    export.add_argument("--resolution", type=int, default=None,
                        help="mesh on a grid this many samples along the part's "
                        "longest side, instead of in print-sized facets")
    export.add_argument("--cell", type=float, default=PRINT_CELL,
                        help="facet size to print from, in mm (default "
                        f"{PRINT_CELL})")
    export.set_defaults(handler=command_export)

    inspect = subparsers.add_parser("inspect", help="show parameters, features, geometry")
    add_common(inspect)
    inspect.set_defaults(handler=command_inspect)

    sweep = subparsers.add_parser("sweep", help="vary a parameter, report cache behaviour")
    add_common(sweep)
    sweep.add_argument("--parameter", required=True)
    sweep.add_argument("--start", required=True, help="e.g. 4mm")
    sweep.add_argument("--stop", required=True, help="e.g. 10mm")
    sweep.add_argument("--steps", type=int, default=7)
    sweep.set_defaults(handler=command_sweep)

    accept = subparsers.add_parser(
        "accept", help="approve the assumptions holding a design back"
    )
    accept.add_argument("document", help="path to a ForgeIR JSON document")
    accept.add_argument(
        "--assumption",
        action="append",
        metavar="ID",
        help="accept this assumption; repeat for several",
    )
    accept.add_argument(
        "--all", action="store_true", help="accept every blocking assumption"
    )
    accept.add_argument(
        "--out", help="write the accepted document here instead of in place"
    )
    accept.set_defaults(handler=command_accept)

    capability = subparsers.add_parser(
        "capability", help="print the truthful capability matrix"
    )
    capability.set_defaults(handler=command_capability)

    return parser


#: What a console that is not UTF-8 shows for the characters Forge and the
#: model write: the evidence's "\u00b1", a model's "\u03c3" and "\u2248".
_PLAIN = {
    "\u00b1": "+/-", "\u00d7": "x", "\u00b0": " deg", "\u00b2": "^2",
    "\u00b3": "^3", "\u00b5": "u", "\u03bc": "u", "\u03c3": "sigma",
    "\u03c4": "tau", "\u03b5": "eps", "\u03b8": "theta", "\u03c0": "pi",
    "\u0394": "delta", "\u03b4": "delta", "\u2248": "~", "\u2264": "<=",
    "\u2265": ">=", "\u2260": "!=", "\u2192": "->", "\u2190": "<-",
    "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": "*",
    "\u2022": "*", "\u221a": "sqrt", "\u221e": "inf", "\u00bd": "1/2",
    "\u00bc": "1/4", "\u00be": "3/4", "\u00d8": "dia ", "\u2300": "dia ",
    "\u00a0": " ",
}


def _plain(error: UnicodeError) -> tuple[str, int]:
    text = error.object[error.start:error.end]  # type: ignore[attr-defined]
    return "".join(_PLAIN.get(c, "?") for c in text), error.end  # type: ignore[attr-defined]


def _a_console_that_cannot_fail() -> None:
    """Printing never stops a run, and what it prints can be read.

    A Windows console piped through PowerShell is written in its code page,
    and a brief with a character the page lacks -- a "\u2265", an arrow, a
    letter of another alphabet -- stopped `forge design` before it began, on
    printing the brief back. And a character the page does have is still
    shown in another page by the console reading the pipe: every "\u00b1"
    in the evidence came out as a block.

    So a console that is not UTF-8 is written plain ASCII, which reads the
    same in every code page: "\u00b1" as "+/-", "\u2265" as ">=", and
    anything with no plain spelling as "?". A UTF-8 console is left as it
    is. The run's files are written in UTF-8 either way."""
    import codecs

    try:
        codecs.lookup_error("forge_plain")
    except LookupError:
        codecs.register_error("forge_plain", _plain)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        encoding = str(getattr(stream, "encoding", "") or "").lower()
        try:
            if encoding.replace("-", "").replace("_", "") in ("utf8",
                                                              "utf8sig"):
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="ascii", errors="forge_plain")
        except Exception:  # noqa: BLE001 - a stream that cannot be told
            pass


def main(argv: list[str] | None = None) -> int:
    _a_console_that_cannot_fail()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - the CLI is the last line of defence
        detail = getattr(exc, "as_dict", None)
        if callable(detail):
            print(json.dumps(detail(), indent=2), file=sys.stderr)
        else:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED

