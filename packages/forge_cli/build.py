"""``forge build``: a confirmed spec to a judged part and its files, with no model call (docs/V2-stage4.md, section 9).

1. The confirmed spec is unlocked: its brief numbered afresh, its digest and
   every spec check run again. A person's confirmation counts only with its
   seal (:mod:`forge_cli.seal`); without one the spec builds as a draft.
2. The build gets a folder of its own: ``--out`` (new or empty), or a fresh
   ``build`` folder in the run's folder. Nothing of an earlier build, or of
   yours, is written over.
3. The judge before building (:class:`forge_checks.judge.Judge`): a shape
   that can't be made ends the run CAN'T, one the judge can't make holds it.
4. The plan and the build (:func:`forge_plan.plan`,
   :func:`forge_occ.planned.build_plan`): a gap ends it UNABLE.
5. The judge on the B-rep; the second kernel's agreement; each file asked
   for written, read back, held to the part and judged as a view.
6. The ending, the record, the files released (only for an ending that
   releases them), the verdict last.

Exit codes: 0 the files released (VERIFIED, VERIFIED EXCEPT or BUILT TO
DRAFT); 1 HELD; 2 a command line or a confirmed spec refused, or an error of
Forge's own; 3 UNABLE; 4 CAN'T.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge_numeric import vector as fv

__all__ = [
    "ENDINGS",
    "EXIT_CANT",
    "EXIT_ERROR",
    "EXIT_HELD",
    "EXIT_RELEASED",
    "EXIT_UNABLE",
    "FORMATS",
    "Confirmed",
    "RefusedError",
    "add_build_parser",
    "build_folder",
    "export_tolerance",
    "file_stem",
    "read_confirmed",
    "run_build",
]

EXIT_RELEASED = 0
EXIT_HELD = 1
EXIT_ERROR = 2
EXIT_UNABLE = 3
EXIT_CANT = 4

#: Each ending, and its exit code.
ENDINGS = {
    "VERIFIED": EXIT_RELEASED,
    "VERIFIED EXCEPT": EXIT_RELEASED,
    "BUILT TO DRAFT": EXIT_RELEASED,
    "HELD": EXIT_HELD,
    "UNABLE": EXIT_UNABLE,
    "CAN'T": EXIT_CANT,
}
#: The endings whose files are released beside the verdict.
RELEASED = frozenset({"VERIFIED", "VERIFIED EXCEPT", "BUILT TO DRAFT"})
#: The files a build can ship, in the order they are made.
FORMATS = ("step", "stl", "3mf")
#: The STL's and 3MF's deflection: a twentieth of the smallest half-band, within these (mm; 9.4).
FINEST, COARSEST, SHARE = 0.0005, 0.01, 20.0
#: Their angular deflection (radians).
ANGULAR = 0.1
#: Names Windows keeps for its devices: no file may be called them.
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{d}{n}" for d in ("com", "lpt") for n in range(1, 10)}
)
#: What a confirmed.json must hold.
_FIELDS = {"by": str, "strict": bool, "digest": str, "brief": str, "spec": dict}

Say = Callable[[str], None]


class RefusedError(Exception):
    """A command line or a confirmed spec refused: nothing is built (exit 2)."""


# ----------------------------------------------------------------------
# The confirmed spec, and the folder
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Confirmed:
    """A confirmed spec unlocked for building: whether a person's sealed confirmation stands behind it, and if not, why."""

    spec: Any  # forge_spec.lock.ConfirmedSpec
    path: Path
    by_person: bool
    why_draft: str
    sealed: bool


def read_confirmed(source: Path, sealer: Any) -> Confirmed:
    """The confirmed spec at ``source`` (a run folder, or its ``confirmed.json``), unlocked; refused (:class:`RefusedError`) when it can't be read or was changed."""
    from forge_spec import number_words
    from forge_spec.lock import LockError, unlock

    path = source / "confirmed.json" if source.is_dir() else source
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RefusedError(f"{path} can't be read: {error}") from None
    if not isinstance(record, dict):
        raise RefusedError(f"{path} isn't a confirmed spec: no object")
    for name, kind in _FIELDS.items():
        if not isinstance(record.get(name), kind):
            raise RefusedError(
                f"{path} isn't a confirmed spec: its {name} is missing or not a {kind.__name__}"
            )
    answers_from = record.get("answers_from")
    if answers_from is not None and (
        isinstance(answers_from, bool) or not isinstance(answers_from, int)
    ):
        raise RefusedError(
            f"{path} isn't a confirmed spec: its answers_from is not a number"
        )
    by = record["by"]
    try:
        brief = number_words(record["brief"], answers_from=answers_from)
        spec = unlock(
            record["spec"], brief, record["digest"], by=by, strict=record["strict"]
        )
    except (LockError, ValueError) as error:
        raise RefusedError(f"{path}: the confirmed spec is refused: {error}") from None
    sealed = (
        by == "person"
        and sealer is not None
        and sealer.holds(spec.digest, record.get("seal"))
    )
    if by != "person":
        why = "locked as a draft: no person confirmed it"
    elif sealed:
        why = ""
    elif "seal" not in record:
        why = "its confirmation has no seal: built as a draft (confirm it with forge spec here to verify it)"
    else:
        why = "its seal isn't this installation's: built as a draft (confirm it with forge spec here to verify it)"
    return Confirmed(spec, path, sealed, why, sealed)


def build_folder(run: Path, out: Path | None) -> Path:
    """The build's own folder, made: ``out`` (refused unless new or empty), or a fresh ``build`` folder in ``run``."""
    if out is not None:
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise RefusedError(
                f"--out {out} isn't a new or empty folder: a build is never written over anything"
            )
        out.mkdir(parents=True, exist_ok=True)
        return out
    found, n = run / "build", 1
    while True:
        try:
            found.mkdir(parents=True)
            return found
        except FileExistsError:
            n += 1
            found = run / f"build-{n}"


def file_stem(name: str) -> str:
    """A spec's name as a file's name (9.4): lower-case ASCII letters, digits and dashes, at most 64; ``part`` when none is left or Windows keeps the name."""
    stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].strip("-")
    return "part" if not stem or stem in _RESERVED else stem


#: Round a check's own surface, how far its finer mesh tolerance holds (mm; docs/V2-stage4.md, 13.10).
AROUND = 1.0


def export_tolerance(suite: Any) -> Any:
    """The meshes' tolerance (9.4): a twentieth of the half-band of a size each check holds, and as fine as a cone's angle needs to be measured on them, from 0.0005 to 0.01 mm; 0.1 rad.

    A check measured on its own surface alone (a diameter, a cone's angle)
    asks it there: in the box round that surface, grown by :data:`AROUND`,
    where finer than the rest ask everywhere (docs/V2-stage4.md, 13.10).
    """
    from forge_checks.kinds.angle import mesh_deflection
    from forge_checks.kinds.surfaces import Cone
    from forge_occ.export import ExportTolerance

    everywhere = [COARSEST]
    there: list[tuple[Any, float]] = []
    for c in suite.checks:
        if c.tolerance is None or (
            c.kind == "angle" and not isinstance(c.target, Cone)
        ):
            continue
        if c.kind == "angle":
            need = max(mesh_deflection(c.target, c.tolerance), FINEST)
        else:
            need = max(c.tolerance.band / 2 / SHARE, FINEST)
        box = _own_surface(c.target) if c.kind in ("angle", "diameter") else None
        if box is None:
            everywhere.append(need)
        else:
            there.append((box, need))
    linear = max(min(everywhere), FINEST)
    return ExportTolerance(
        linear, ANGULAR, tuple((b, n) for b, n in there if n < linear)
    )


def _own_surface(target: Any) -> Any:
    """The box round the surface a diameter or a cone's angle is measured on, grown by :data:`AROUND`; None for any other."""
    import numpy as np
    from forge_checks.kinds.diameter import Across
    from forge_checks.kinds.surfaces import Ball, Cone, Round
    from forge_checks.view import Box

    if isinstance(target, Across):
        target = target.cone
    if isinstance(target, Ball):
        (x, y, z), reach = target.centre, target.radius + AROUND
        return Box((x - reach, y - reach, z - reach), (x + reach, y + reach, z + reach))
    if isinstance(target, Round):
        ends, radii = (target.start, target.end), (target.radius, target.radius)
    elif isinstance(target, Cone):
        ends, radii = target.ends, target.radii
    else:
        return None
    axis = np.asarray(target.axis, dtype=np.float64)
    axis = axis / fv.norm(axis)
    # A circle of radius r square to the axis reaches r·√(1 - a_k²) along each frame axis k.
    across = np.sqrt(np.maximum(1.0 - axis * axis, 0.0))
    rims = [np.asarray(target.centre) + s * axis for s in ends]
    lo = (
        np.min([c - r * across for c, r in zip(rims, radii, strict=True)], axis=0)
        - AROUND
    )
    hi = (
        np.max([c + r * across for c, r in zip(rims, radii, strict=True)], axis=0)
        + AROUND
    )
    return Box(
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
    )


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------
@dataclass
class _Run:
    """What a build found, as it goes: written into the record and the verdict at the end."""

    confirmed: Confirmed
    folder: Path
    seed: int
    formats: tuple[str, ...]
    say: Say
    seconds: dict[str, float] = field(default_factory=dict)
    held: list[dict[str, Any]] = field(default_factory=list)
    views: list[Any] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    made: dict[str, bytes] = field(default_factory=dict)
    agreement: dict[str, Any] | None = None
    build: dict[str, Any] | None = None
    judge: Any = None
    cant: str | None = None
    gap: dict[str, str] | None = None
    tolerance: Any = None

    def timed(self, stage: str, started: float) -> None:
        self.seconds[stage] = round(time.perf_counter() - started, 3)

    def hold(
        self, view: str, detector: str, item: str | None, what: str, why: str
    ) -> None:
        self.held.append({"view": view, "detector": detector, "item": item, "what": what, "verdict": "fail",
                          "why": why})  # fmt: skip


def run_build(source: Path, *, out: Path | None = None, formats: Sequence[str] = FORMATS, seed: int | None = None,
              sealer: Any = None, say: Say = print) -> int:  # fmt: skip
    """Build and judge a confirmed spec (see the module's docstring); the exit code."""
    try:
        confirmed = read_confirmed(source, sealer)
        run_folder = source if source.is_dir() else source.parent
        folder = build_folder(run_folder, out)
    except RefusedError as error:
        say(f"Refused: {error}")
        return EXIT_ERROR
    run = _Run(
        confirmed,
        folder,
        secrets.randbits(63) if seed is None else int(seed),
        tuple(formats),
        say,
    )
    spec = confirmed.spec.spec
    say(f"Spec     : {spec.name!r}, {len(spec.items)} item(s), digest {confirmed.spec.digest[:12]}…, "
        + ("confirmed by a person, sealed" if confirmed.by_person else confirmed.why_draft))  # fmt: skip
    say(f"Build    : {folder}")
    try:
        ending = _build(run)
    except Exception as error:  # Forge's own error: said, recorded, exit 2
        detail = getattr(error, "as_dict", None)
        record = {"error": type(error).__name__, "message": str(error),
                  "detail": detail() if callable(detail) else None}  # fmt: skip
        _write(folder / "record" / "error.json", record)
        say(f"Error    : {type(error).__name__}: {error}")
        say(
            "No verdict: Forge's own error stopped the build (record/error.json says what)."
        )
        return EXIT_ERROR
    return ENDINGS[ending]


def _build(run: _Run) -> str:
    from forge_checks.judge import Judge
    from forge_checks.oracle import CannotMakeError, OracleError
    from forge_checks.place import PlaceError
    from forge_occ.planned import build_plan
    from forge_plan import plan

    confirmed = run.confirmed.spec
    started = time.perf_counter()
    try:
        run.judge = Judge.of(confirmed.spec)
    except CannotMakeError as why:
        run.cant = str(why)
        run.timed("judge before building", started)
        return _finish(run, "CAN'T")
    except (OracleError, PlaceError) as why:
        run.hold("the spec", "oracle", None, "the spec's shape", f"the judge can't make the shape the spec asks "
                 f"for, so it can't judge it: {why}")  # fmt: skip
        run.timed("judge before building", started)
        return _finish(run, "HELD")
    run.timed("judge before building", started)
    judge = run.judge
    run.say(f"Judge    : {len(judge.suite.checks)} checks, {_radii(judge.suite)}"
            + (f"; {len(judge.unchecked)} thing(s) of the spec unchecked" if judge.unchecked else ""))  # fmt: skip

    started = time.perf_counter()
    planned = plan(confirmed)
    built = build_plan(planned)
    run.timed("plan and build", started)
    run.build = _build_record(built)
    document = planned.document(built.choice) if built.result is not None else None
    if document is not None:
        _write_text(run.folder / "record" / "document.json", document.to_json())
    run.say(
        f"Plan     : {len(planned.items)} item(s), {built.builds} build(s), {len(built.refusals)} refusal(s)"
    )
    if built.gap is not None:
        run.gap = {"item": built.gap.item, "why": built.gap.reason}
        return _finish(run, "UNABLE")
    assert built.result is not None and document is not None
    _judge_brep(run, built.result.shape)
    _agreement(run, document, built.result)
    _files(run, built.result.shape, file_stem(confirmed.spec.name))
    if run.held:
        return _finish(run, "HELD")
    if not run.confirmed.by_person:
        return _finish(run, "BUILT TO DRAFT")
    return _finish(run, "VERIFIED EXCEPT" if judge.unchecked else "VERIFIED")


def _build_record(built: Any) -> dict[str, Any]:
    traces = (
        [t.as_dict() for t in built.result.traces] if built.result is not None else []
    )
    gap = (
        None if built.gap is None else {"item": built.gap.item, "why": built.gap.reason}
    )
    return {"made_by": dict(built.made_by), "choice": dict(built.choice), "builds": built.builds,
            "refusals": [{"item": r.item, "construction": r.construction, "step": r.step, "error": r.error}
                         for r in built.refusals],
            "gap": gap, "traces": traces}  # fmt: skip


def _judged(run: _Run, view: Any, name: str) -> None:
    """Judge one view, note what holds the part, and say how it went."""
    started = time.perf_counter()
    found = run.judge.view(view, name, run.seed)
    run.timed(f"judge {name}", started)
    run.views.append(found)
    run.held += [f.as_dict() for f in found.held]
    passed = sum(1 for e in found.evidence if e.verdict.value == "pass")
    state = "passed" if found.passed else f"HELD ({len(found.held)} reason(s))"
    run.say(f"{name:9s}: {passed} of {len(found.evidence)} checks, face accounting ({found.accounting.built.points:,}"
            f" points), topology, volume, fresh probes: {state}")  # fmt: skip


def _judge_brep(run: _Run, shape: Any) -> None:
    from forge_checks.view import ViewProxy
    from forge_occ.view import BrepView

    _judged(run, ViewProxy(BrepView(shape)), "B-rep")


def _agreement(run: _Run, document: Any, result: Any) -> None:
    """The second kernel's opinion: the implicit kernel builds the document down-converted, and the two parts are held together."""
    from forge_occ.agreement import agree

    started = time.perf_counter()
    try:
        report = agree(document, "part", exact=result)
    except (
        Exception
    ) as error:  # the second kernel's failure holds the part, it doesn't stop the run
        run.agreement = {"holds": False, "error": f"{type(error).__name__}: {error}"}
        run.hold(
            "second kernel",
            "agreement",
            None,
            "agreement",
            f"the second kernel couldn't judge it: {error}",
        )
        run.timed("second kernel", started)
        run.say(f"Second kernel: couldn't build it ({type(error).__name__}): HELD")
        return
    run.timed("second kernel", started)
    run.agreement = report.as_dict()
    if not report.holds:
        why = (
            [f"{report.disagreements} point(s) disagree"]
            if report.disagreements
            else []
        )
        if not report.volume.get("holds", True):
            why.append("the volumes don't agree")
        if not report.names.get("holds", True):
            why.append(
                f"names missing: {', '.join(report.names.get('missing', [])[:5])}"
            )
        if not report.topology.get("holds", True):
            why.append("the topology doesn't agree")
        run.hold(
            "second kernel",
            "agreement",
            None,
            "agreement",
            "; ".join(why) or "it doesn't agree",
        )
    run.say(
        f"Second kernel: {report.compared:,} points compared: "
        + ("agrees" if report.holds else "HELD")
    )


def _files(run: _Run, shape: Any, stem: str) -> None:
    """Each file asked for: written, read back and held to the part by the exporter, then judged as a view."""
    from forge_occ.errors import OperationError

    run.tolerance = export_tolerance(run.judge.suite)
    meshed: Any = None
    for kind in run.formats:
        name = f"{stem}.{kind}"
        started = time.perf_counter()
        try:
            if kind == "step":
                data, view, check = _step(shape, stem)
            else:
                if meshed is None:
                    from forge_occ.export import mesh_part

                    meshed = mesh_part(shape, run.tolerance)
                data, view, check = _mesh(shape, meshed, kind, stem, run.tolerance)
        except OperationError as error:
            run.timed(f"file {name}", started)
            run.files.append(
                {
                    "name": name,
                    "format": kind,
                    "error": str(error),
                    "detail": error.as_dict(),
                }
            )
            run.hold(
                name,
                "file",
                None,
                name,
                f"the file can't be written or read back as the part: {error}",
            )
            run.say(f"{name}: can't be written or read back: {error}: HELD")
            continue
        run.made[name] = data
        run.files.append({"name": name, "format": kind, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "read_back": check})  # fmt: skip
        run.timed(f"file {name}", started)
        _judged(run, view, name)


def _step(shape: Any, stem: str) -> tuple[bytes, Any, dict[str, Any]]:
    from forge_checks.view import ViewProxy
    from forge_occ.export import StepPart, check_step, write_step
    from forge_occ.view import BrepView

    parts = [StepPart(stem, shape)]
    data = write_step(parts)
    found, report = check_step(data, parts)
    view = ViewProxy(BrepView(found.parts[stem], source="step-file"))
    return data, view, {"differences": report.parts[stem]}


def _mesh(
    shape: Any, meshed: Any, kind: str, stem: str, tolerance: Any
) -> tuple[bytes, Any, dict[str, Any]]:
    import numpy as np
    from forge_checks.mesh import Mesh
    from forge_checks.readers import read_3mf, read_stl
    from forge_checks.view import ViewProxy
    from forge_occ.export import (
        check_mesh_file,
        file_view,
        plate_shift,
        stl_bytes,
        threemf_bytes,
    )

    if kind == "stl":
        shift = (0.0, 0.0, 0.0)
        data = stl_bytes(meshed.mesh, stem)
        triangles = read_stl(data).triangles
    else:
        shift = plate_shift(meshed.mesh)
        data = threemf_bytes(meshed.mesh, stem, shift)
        triangles = read_3mf(data).triangles
    check = check_mesh_file(data, shape, meshed, tolerance, shift=shift)
    # Judged where the spec has it: moved back by the shift Forge wrote, never by the file's own word.
    mesh = Mesh.from_triangles(triangles - np.asarray(shift))
    view = ViewProxy(file_view(mesh, tolerance))
    return data, view, {"triangles": check.triangles, "deviation": check.deviation, "volume": list(check.volume),
                        "exact_volume": check.exact_volume, "shift": list(shift)}  # fmt: skip


# ----------------------------------------------------------------------
# The ending, the record and the verdict
# ----------------------------------------------------------------------
def _finish(run: _Run, ending: str) -> str:
    from forge_occ.backend import BACKEND_IDENTITY

    from forge_cli import __version__

    confirmed = run.confirmed
    judge = run.judge
    released = ending in RELEASED
    files = []
    for entry in run.files:
        shipped = released and entry["name"] in run.made
        if shipped:
            _release(run.folder / entry["name"], run.made[entry["name"]])
        elif entry["name"] in run.made:
            # Kept to look at, never beside a verdict that doesn't release it.
            _write_bytes(
                run.folder / "record" / "files" / entry["name"], run.made[entry["name"]]
            )
        files.append(
            {
                **{k: v for k, v in entry.items() if k != "read_back"},
                "released": shipped,
            }
        )
    brep = next((v for v in run.views if v.name == "B-rep"), None)
    verdict = {
        "ending": ending, "exit": ENDINGS[ending],
        "spec": {"name": confirmed.spec.spec.name, "digest": confirmed.spec.digest, "by": confirmed.spec.by,
                 "strict": confirmed.spec.strict, "sealed": confirmed.sealed,
                 "built_as": "person" if confirmed.by_person else "draft", "why_draft": confirmed.why_draft,
                 "from": str(confirmed.path)},
        "forge": {"version": __version__, "kernel": BACKEND_IDENTITY},
        "probe_seed": run.seed,
        "cant": run.cant, "gap": run.gap,
        "held": run.held,
        "items": _items(judge, run.views) if judge is not None else [],
        "unchecked": [u.as_dict() for u in judge.unchecked] if judge is not None else [],
        "checked_otherwise": [u.as_dict() for u in judge.held_otherwise] if judge is not None else [],
        "not_cross_checked": sorted({n for v in run.views for n in v.not_cross_checked}),
        "surface": _surface(brep),
        "export_tolerance": None if run.tolerance is None else {
            "linear": run.tolerance.linear, "angular": run.tolerance.angular,
            "finer": [{"lo": list(b.lo), "hi": list(b.hi), "linear": d} for b, d in run.tolerance.finer]},
        "files": files,
        "seconds": run.seconds,
    }  # fmt: skip
    record = run.folder / "record"
    if run.build is not None:
        _write(record / "build.json", run.build)
    _write(record / "judge.json", {"probe_seed": run.seed, "views": [v.as_dict() for v in run.views],
                                   "agreement": run.agreement, "files": run.files,
                                   "unchecked": verdict["unchecked"]})  # fmt: skip
    _write_text(run.folder / "verdict.md", _markdown(verdict))
    # The verdict last, whole: a folder without one is a build that didn't finish.
    _write(run.folder / "verdict.json.part", verdict)
    os.replace(run.folder / "verdict.json.part", run.folder / "verdict.json")
    _say_ending(run.say, verdict)
    return ending


def _items(judge: Any, views: Sequence[Any]) -> list[dict[str, Any]]:
    classes = judge.classes()
    return [{"item": item.id, "kind": item.kind, "class": None if classes.get(item.id) is None
             else classes[item.id].value, "views": {v.name: v.item_held(item.id) for v in views}}
            for item in judge.spec.items]  # fmt: skip


def _radii(suite: Any) -> str:
    """The coverage radius everywhere, and the finer one round each item that asks for one (docs/V2-stage4.md, 13.10)."""
    finer: dict[str, float] = {}
    for f in suite.finer:
        finer[f.item] = min(finer.get(f.item, f.radius), f.radius)
    round_items = ", ".join(f"{r:g} mm round {item}" for item, r in finer.items())
    return f"coverage radius {suite.radius:g} mm" + (
        f" ({round_items})" if finer else ""
    )


def _surface(brep: Any) -> dict[str, Any] | None:
    """The share of the B-rep's surface checked exactly and within bounds: face accounting's built points (9.3)."""
    if brep is None or not brep.accounting.built.points:
        return None
    tally = brep.accounting.built
    return {"points": tally.points, "exact": (tally.exact + tally.witnessed) / tally.points,
            "bounded": tally.bounded / tally.points, "radius": brep.accounting.radius,
            "finest": brep.accounting.finest}  # fmt: skip


def _say_ending(say: Say, verdict: dict[str, Any]) -> None:
    ending = verdict["ending"]
    if ending == "CAN'T":
        say(f"CAN'T: the shape can't be made: {verdict['cant']}")
    elif ending == "UNABLE":
        say(f"UNABLE: {verdict['gap']['item']}: {verdict['gap']['why']}")
    elif ending == "HELD":
        say(f"HELD: {len(verdict['held'])} reason(s)")
        for found in verdict["held"][:20]:
            where = f"{found['item']}, " if found.get("item") else ""
            say(
                f"  - {found['view']}, {where}{found['what']}: {found['verdict']}: {found['why'][:300]}"
            )
    else:
        released = [f["name"] for f in verdict["files"] if f["released"]]
        say(
            f"{ending}: every check passed on every view; released {', '.join(released) or 'no files'}"
        )
        if verdict["spec"]["why_draft"]:
            say(f"  ({verdict['spec']['why_draft']})")
        for u in verdict["unchecked"]:
            say(
                f"  unchecked: {u['item']}"
                + (f".{u['field']}" if u["field"] else "")
                + f": {u['why']}"
            )


def _markdown(verdict: dict[str, Any]) -> str:
    """The verdict for a person."""
    spec = verdict["spec"]
    lines = [f"# {verdict['ending']}: {spec['name']}", "",
             f"Spec digest `{spec['digest']}`, "
             + ("confirmed by a person, sealed." if spec["built_as"] == "person" else f"{spec['why_draft']}."),
             f"Forge {verdict['forge']['version']}, {verdict['forge']['kernel']}; fresh probes from seed "
             f"{verdict['probe_seed']}.", ""]  # fmt: skip
    if verdict["cant"]:
        lines += ["## Why it can't be made", "", verdict["cant"], ""]
    if verdict["gap"]:
        lines += [
            "## The gap",
            "",
            f"{verdict['gap']['item']}: {verdict['gap']['why']}",
            "",
        ]
    if verdict["held"]:
        lines += ["## What holds it", ""]
        lines += [f"- **{h['view']}**, {h['detector']}" + (f", {h['item']}" if h.get("item") else "")
                  + f": {h['what']}: {h['verdict']}: {h['why']}" for h in verdict["held"]]  # fmt: skip
        lines.append("")
    if verdict["items"]:
        views = list(verdict["items"][0]["views"])
        lines += ["## Items", "", "| Item | Kind | Class | " + " | ".join(views) + " |",
                  "|---|---|---|" + "---|" * len(views)]  # fmt: skip
        for item in verdict["items"]:
            # "passed", not "held": HELD is an ending, a part held back.
            passed = ["passed" if item["views"][v] else "**not passed**" for v in views]
            lines.append(f"| {item['item']} | {item['kind']} | {item['class'] or 'no checks'} | " + " | ".join(passed)
                         + " |")  # fmt: skip
        lines.append("")
    if verdict["unchecked"]:
        lines += ["## Not checked", ""]
        lines += [f"- {u['item']}" + (f".{u['field']}" if u["field"] else "") + f": {u['why']}"
                  for u in verdict["unchecked"]]  # fmt: skip
        lines.append("")
    if verdict["checked_otherwise"]:
        lines += ["## Checked otherwise (no check of their own)", ""]
        lines += [
            f"- {u['item']}.{u['field']}: {u['why']}"
            for u in verdict["checked_otherwise"]
        ]
        lines.append("")
    if verdict["not_cross_checked"]:
        lines += ["## Not cross-checked (no ending changes for these)", ""]
        lines += [f"- {n}" for n in verdict["not_cross_checked"]]
        lines.append("")
    if verdict["surface"]:
        s = verdict["surface"]
        # A record from before finer boxes has no finest.
        finest = s.get("finest", s["radius"])
        finer = (
            f", {finest:g} mm round its smallest features"
            if finest < s["radius"]
            else ""
        )
        lines += ["## The surface", "", f"Of {s['points']:,} points covering the B-rep (every point within "
                  f"{s['radius']:g} mm of one{finer}): {100 * s['exact']:.1f}% checked exactly, "
                  f"{100 * s['bounded']:.1f}% within bounds.", ""]  # fmt: skip
    if verdict["files"]:
        lines += ["## Files", ""]
        for f in verdict["files"]:
            if "error" in f:
                lines.append(f"- {f['name']}: not made: {f['error']}")
            else:
                state = (
                    "released"
                    if f["released"]
                    else "kept in record/files, not released"
                )
                lines.append(
                    f"- {f['name']}: {f['bytes']:,} bytes, SHA-256 `{f['sha256']}`, {state}"
                )
        lines.append("")
    if verdict["seconds"]:
        lines += ["## Time", ""]
        lines += [
            f"- {stage}: {seconds:.1f} s"
            for stage, seconds in verdict["seconds"].items()
        ]
        lines.append("")
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    """A value JSON can write: NumPy's numbers and arrays as Python's."""
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return str(value)


def _write(path: Path, content: Any) -> None:
    _write_text(path, json.dumps(content, indent=2, ensure_ascii=False, default=_plain))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _release(path: Path, data: bytes) -> None:
    """A file released beside the verdict: created afresh, never over an existing file."""
    with open(path, "xb") as out:
        out.write(data)


# ----------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------
def _formats(text: str) -> tuple[str, ...]:
    asked = [f.strip().lower() for f in text.split(",") if f.strip()]
    unknown = sorted(set(asked) - set(FORMATS))
    if unknown or not asked:
        raise argparse.ArgumentTypeError(
            f"--formats takes {', '.join(FORMATS)} (one at least): not {text!r}"
        )
    return tuple(f for f in FORMATS if f in asked)


def command_build(args: argparse.Namespace) -> int:
    from .seal import Sealer, SealError

    try:
        sealer = Sealer.of_install(create=False)
    except SealError as error:
        print(
            f"Seal     : can't be read ({error}): a person's confirmation can't be told here"
        )
        sealer = None
    out = Path(args.out) if args.out else None
    return run_build(
        Path(args.source), out=out, formats=args.formats, seed=args.seed, sealer=sealer
    )


def add_build_parser(subparsers: Any) -> argparse.ArgumentParser:
    """``forge build``: a confirmed spec to a judged part and its files (V2)."""
    build: argparse.ArgumentParser = subparsers.add_parser(
        "build",
        help="build a confirmed spec, judge it on every view, and release its files (V2)",
        description=(
            "Build a confirmed spec with no model call: the judge's shape and checks, the plan, the build, the "
            "judge on the exact part, the second kernel and every file, and one ending. Exit codes: 0 files "
            "released (VERIFIED, VERIFIED EXCEPT, BUILT TO DRAFT), 1 HELD, 2 refused or an error, 3 UNABLE, "
            "4 CAN'T."
        ),
    )
    build.add_argument("source", help="a run's folder, or its confirmed.json")
    build.add_argument(
        "--out",
        help="a new or empty folder for the build (default: a fresh build folder in the run's)",
    )
    build.add_argument(
        "--formats",
        type=_formats,
        default=FORMATS,
        help="files to make: step,stl,3mf (default all)",
    )
    build.add_argument(
        "--seed",
        type=int,
        help="draw the fresh probes from this seed (default: a new one, recorded)",
    )
    build.set_defaults(handler=command_build)
    return build
