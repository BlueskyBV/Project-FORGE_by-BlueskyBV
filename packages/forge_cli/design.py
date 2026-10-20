"""``forge design`` - a sentence in, an evidence file out.

This is the AI loop at the command line. It builds a provider from flags and
environment, runs the orchestrator, writes every artefact of the run to a
directory, and exits with a code that says what actually happened.

Three things here are deliberate and worth stating plainly.

**The key is never an argument.** There is no ``--api-key`` flag, on purpose. A
key passed on a command line lands in shell history, in ``ps`` output and in CI
logs. Forge reads it from the environment, and nothing that gets written --
report, run log, provenance -- contains it.

**A run that stops to ask a question is not a failure.** It exits ``3``, prints
the questions, and prints the exact command that resumes it with the answers.
That is the state the design loop is *supposed* to reach when the brief is
underspecified, and giving it its own exit code keeps a script from treating
"we could not honestly proceed" as either success or breakage.

**Every run is recorded.** ``--record`` wraps a live provider so its responses
land in a fixture library, which ``--provider fixture`` then replays offline for
free. A real run costs money once; reproducing it costs nothing, and the
reproduction is byte-identical rather than merely similar.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from forge_models import (
    DEFAULT_MODEL,
    AnthropicProvider,
    Budget,
    CancellationToken,
    ConfigurationError,
    FixtureProvider,
    ModelRequest,
    ModelResponse,
    OllamaNativeProvider,
    OpenAICompatibleProvider,
    Provider,
    RecordingProvider,
)
from forge_orchestrator import Orchestrator, OrchestratorConfig, State

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_UNDECIDED = 2
EXIT_QUESTIONS = 3


# ----------------------------------------------------------------------
def build_provider(args: argparse.Namespace) -> Provider:
    """Construct the provider the flags describe, or explain what is missing."""
    budget = Budget(
        max_total_tokens=args.max_tokens,
        max_calls=args.max_calls,
        max_cost_usd=args.max_cost,
    )

    provider: Provider
    if args.provider == "fixture":
        if not args.fixtures:
            raise SystemExit(
                "--provider fixture needs --fixtures DIR, a directory of "
                "recorded responses. Record one first with --record DIR."
            )
        provider = FixtureProvider(args.fixtures, budget=budget)
    elif args.provider == "anthropic":
        provider = AnthropicProvider(
            model=args.model or DEFAULT_MODEL,
            schema_dialect=args.schema_dialect,
            # The run's own `--timeout`, not a fixed three minutes: a design
            # written whole can take longer, and a timed-out call is paid for
            # and then asked again.
            timeout=max(args.timeout, 300.0),
            budget=budget,
            thinking=getattr(args, "thinking", None),
            effort=getattr(args, "effort", None),
        )
        if not provider.is_configured:
            raise SystemExit(
                "no Anthropic API key found. Set ANTHROPIC_API_KEY in this "
                "shell's environment. Forge deliberately has no --api-key "
                "flag: a key on a command line ends up in shell history."
            )
    elif args.provider == "ollama":
        if not args.model:
            raise SystemExit("--provider ollama needs --model")
        # Measured, not assumed: with a required single-value enum placed at
        # the document, every component and every feature, this endpoint
        # returned all three markers and the `openai` shim returned none --
        # under both a five-token prompt and the designer's own. The shim
        # once answered by echoing our schema back as the document. So this
        # is the transport where the schema is actually a grammar.
        provider = OllamaNativeProvider(
            model=args.model,
            base_url=(args.base_url or "http://localhost:11434").removesuffix("/v1"),
            context_window=args.context_window or 32768,
            timeout=args.timeout,
            budget=budget,
        )
    elif args.provider == "openai":
        if not args.model:
            raise SystemExit("--provider openai needs --model")
        provider = OpenAICompatibleProvider(
            model=args.model,
            base_url=args.base_url or "http://localhost:11434/v1",
            api_key_env=args.api_key_env,
            structured_mode=args.structured_mode,
            schema_dialect=args.schema_dialect,
            context_window=args.context_window,
            timeout=args.timeout,
            is_remote=not _is_local(args.base_url or ""),
            allow_schema_reduction=not args.exact_schema,
            budget=budget,
        )
    else:  # pragma: no cover - argparse constrains the choices
        raise SystemExit(f"unknown provider '{args.provider}'")

    if args.max_cost is not None and not _can_price(args, provider):
        # A cost ceiling the provider cannot measure against is not a
        # ceiling: the budget's cost check never fired, and the flag the help
        # text calls a hard stop was a no-op for a local model, an
        # OpenAI-compatible endpoint, a replay, or a Claude model outside
        # the price table. Refused before anything is spent, with the bound
        # that does work named.
        raise SystemExit(
            f"--max-cost cannot be enforced with --provider {args.provider}"
            + (f" and --model {args.model}: no price is known for it"
               if args.provider == "anthropic" else
               ": this provider reports no price for its calls")
            + ". Bound the run with --max-tokens or --max-calls instead"
            + (", or add the model to forge_models.anthropic.PRICE_TABLE."
               if args.provider == "anthropic" else "."))

    if args.record:
        Path(args.record).mkdir(parents=True, exist_ok=True)
        provider = RecordingProvider(provider, args.record)
    return provider


def _can_price(args: argparse.Namespace, provider: Provider) -> bool:
    """Whether this provider can estimate the cost of its calls."""
    if args.provider != "anthropic":
        return False
    from forge_models.anthropic import _estimate_cost
    from forge_models import Usage

    return _estimate_cost(provider.info.model, Usage(1, 1)) is not None


def _is_local(base_url: str) -> bool:
    return bool(re.search(r"//(localhost|127\.0\.0\.1|\[::1\])\b", base_url))



class _Progress(Provider):
    """Prints a heartbeat while a call is in flight.

    A local model can take ten minutes to write one document. The observers
    that report a finished call cannot help during it, so the terminal sits
    blank and the only available conclusion is "this has hung". It has not; it
    is thinking at six tokens a second, and saying so is the difference between
    waiting and killing the run.

    A wrapper rather than a change to Provider: retries, budget and accounting
    all belong to the provider underneath, and this one only watches the clock.
    """

    def __init__(self, inner: Provider, *, interval: float = 15.0) -> None:
        self._inner = inner
        self._interval = interval
        # Shared, not copied: the orchestrator reads the budget through this
        # object and must see the same one the calls are recorded against.
        self.retry = inner.retry
        self.budget = inner.budget
        self.observers = inner.observers

    @property
    def info(self):  # type: ignore[override]
        return self._inner.info

    def _send(self, request: ModelRequest) -> ModelResponse:  # pragma: no cover
        return self._inner._send(request)  # noqa: SLF001

    def complete(self, request: ModelRequest, *, cancellation=None) -> ModelResponse:
        stop = threading.Event()
        watcher = threading.Thread(
            target=self._tick, args=(request, stop), daemon=True
        )
        watcher.start()
        try:
            return self._inner.complete(request, cancellation=cancellation)
        finally:
            stop.set()

    def _tick(self, request: ModelRequest, stop: threading.Event) -> None:
        started = time.time()
        while not stop.wait(self._interval):
            # What the wait is: the model reading the prompt, or writing --
            # and how far. A count that stops climbing is a stall; one that
            # climbs past any document's size is a runaway.
            written = getattr(self._inner, "tokens_so_far", None)
            phase = getattr(self._inner, "phase_so_far", "") or "written"
            # Before a token arrives the stream still says which: Claude
            # sends a tool's input a whole field at a time, so a design's one
            # large `document` field arrives at the end, and "0 tokens" held
            # the line at "reading the prompt" through thinking and writing.
            doing = ("" if written is None else
                     ", thinking" if phase == "thinking" and not written else
                     ", writing the answer" if phase == "writing"
                     and not written else
                     ", reading the prompt" if not written else
                     f", {phase}, about {written} tokens" if phase != "written"
                     else f", {written} tokens written")
            print(
                f"       {_what_the_call_is(request)} still running, "
                f"{time.time() - started:.0f}s elapsed{doing}",
                flush=True,
            )


# ----------------------------------------------------------------------
def collect_answers(args: argparse.Namespace) -> dict[str, str]:
    """Answers from ``--answers file.json`` and ``--answer ID=text``.

    Flags win over the file, so a stored answer can be overridden for one run
    without editing the file.
    """
    answers: dict[str, str] = {}
    if args.answers:
        payload = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit(
                f"{args.answers} must contain a JSON object of "
                '{"UNKNOWN_ID": "answer"}'
            )
        answers.update({str(k): str(v) for k, v in payload.items()})
    for item in args.answer or []:
        if "=" not in item:
            raise SystemExit(
                f"answer '{item}' must be written ID=text, e.g. "
                '--answer U1="316 stainless, 2 kN"'
            )
        identifier, _, text = item.partition("=")
        answers[identifier.strip()] = text.strip()
    return answers


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (cleaned[:limit].rstrip("-") or "design")


def _resume_command(brief: str, questions: tuple[Any, ...]) -> str:
    parts = ["forge design", json.dumps(brief)]
    for question in questions:
        parts.append(f"--answer {question.identifier}=<your answer>")
    return " \\\n    ".join(parts)


# ----------------------------------------------------------------------
def write_artifacts(run: Any, directory: Path) -> list[Path]:
    """Persist everything the run produced. Failures are written too.

    A failed run is the one whose record you most want afterwards, so the event
    log, the repair attempts and the failure payload are written whatever the
    outcome.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _write(name: str, make: Any) -> None:
        # Each artefact on its own: one value that will not serialise, or a
        # report that will not render, never costs the run the others.
        try:
            text = make()
            path = directory / name
            path.write_text(text, encoding="utf-8")
            written.append(path)
        except Exception as error:  # noqa: BLE001 - recorded, never fatal
            try:
                (directory / (name + ".error.txt")).write_text(
                    f"{type(error).__name__}: {error}", encoding="utf-8")
            except OSError:
                pass

    _write("run.json", lambda: json.dumps(run.as_dict(), indent=2,
                                          sort_keys=False, default=str))
    _write("run.txt", lambda: run.render(verbose=True))

    if run.document_payload is not None:
        _write(
            "document.forgeir.json",
            lambda: json.dumps(run.document_payload, indent=2,
                               sort_keys=False, default=str),
        )
    if run.report is not None:
        _write("evidence.json", lambda: json.dumps(run.report.as_dict(),
                                                   indent=2, default=str))
        _write("evidence.txt", lambda: run.report.render())
        mesh_path = _write_mesh(run.report, directory)
        if mesh_path is not None:
            written.append(mesh_path)
    pictures = getattr(run, "pictures", None) or []
    if pictures:
        # The part as it finished, as the model last saw it.
        try:
            path = directory / "views.png"
            path.write_bytes(pictures[-1][1])
            written.append(path)
        except OSError:
            pass
    if run.questions:
        _write(
            "questions.json",
            lambda: json.dumps([q.as_dict() for q in run.questions],
                               indent=2, default=str),
        )
    return written


#: Mesh resolution for the artefact written beside a run.
#:
#: Higher than the verification mesh, which is tuned for *comparing* against
#: the octree enclosure rather than for looking at. This one is the file
#: somebody opens.
_ARTEFACT_RESOLUTION = 96


def _write_mesh(report: Any, directory: Path) -> Path | None:
    """Write the part as an STL, whatever the verdict.

    The whole point of the system is a part you can open, and `forge design`
    was writing five files describing one and not the part itself. Exporting it
    meant knowing to run `forge export` afterwards against the document the run
    had just written -- a step nobody should have to be told about.

    Written for a BLOCKED or FAILED run too, deliberately. A design that misses
    a gate is still a design, and looking at it is usually the fastest way to
    understand *why* it missed: the bracket whose bolt pattern repeated the
    whole body is obvious in a viewer and subtle in a gate report.

    Never fatal. A run's record must not be lost because the mesher could not
    find a surface -- which happens exactly when the design encloses nothing,
    and that case is already reported as evidence.
    """
    try:
        from forge_geom import extract_manifold_surface, write_stl

        # Meshed again for printing, in half-millimetre facets: the surface
        # verification read is sized for checking, in cells a fraction of the
        # part's length, and a 287 mm rail's 8.2 mm bolt holes came out of it
        # 7.3 mm across. That one is the fallback, when no fine grid closes.
        mesh, note = _a_surface_to_print(report.part.solid)
        if mesh is None:
            mesh = getattr(report, "mesh", None) or extract_manifold_surface(
                report.part.solid, resolution=_ARTEFACT_RESOLUTION)
        path = directory / f"{report.component_id}.stl"
        write_stl(mesh, path)
        _MESH_NOTES[str(path)] = note
        return path
    except Exception:  # noqa: BLE001 - an artefact, not a result
        return None


#: What each STL written this run is, said beside it in the listing.
_MESH_NOTES: dict[str, str] = {}


def _a_surface_to_print(solid: Any) -> tuple[Any, str]:
    """The surface meshed for printing and a line saying how true it is, or
    (None, why not)."""
    import numpy as np

    from forge_geom import extract_print_surface, surface_deviation

    try:
        mesh = extract_print_surface(solid)
    except Exception:  # noqa: BLE001 - the coarser surface is written instead
        mesh = None
    if mesh is None:
        return None, ("meshed coarse: no fine mesh of it came out closed, so "
                      "holes may print undersize")
    edges = np.linalg.norm(mesh.vertices[mesh.faces[:, 1]]
                           - mesh.vertices[mesh.faces[:, 0]], axis=1)
    facet = float(np.median(edges))
    near = surface_deviation(solid, mesh, quantile=0.99)
    return mesh, (f"{facet:.2f} mm facets for printing, 99% of the surface "
                  f"within {max(near, 0.01):.2f} mm of the design")


def _exit_code(state: State) -> int:
    if state is State.COMPLETED:
        return EXIT_PASS
    if state is State.FAILED:
        return EXIT_FAIL
    if state is State.AWAITING_ANSWERS:
        return EXIT_QUESTIONS
    return EXIT_UNDECIDED


# ----------------------------------------------------------------------
def command_design(args: argparse.Namespace) -> int:
    brief = args.brief.strip()
    if not brief:
        raise SystemExit("the brief is empty; describe the part you want")

    provider = build_provider(args)
    answers = collect_answers(args)

    config = OrchestratorConfig(
        max_compile_repairs=args.repairs,
        max_gate_repairs=args.gate_repairs,
        redesigns=max(0, int(getattr(args, "redesigns", 1))),
        max_gate_repairs_after_a_redesign=max(1, min(args.gate_repairs, 2)),
        stop_on_critical_unknowns=not args.assume,
        output_token_cap=args.max_output_tokens,
        measurement_depth=args.depth,
        mesh_resolution=args.mesh_resolution,
    )

    cancellation = CancellationToken()
    _install_interrupt_handler(cancellation)

    if args.verbose:
        provider.observe(_progress_observer())
        # Outermost, so the heartbeat covers retries and recording too.
        provider = _Progress(provider)

    info = provider.info
    print(f"Provider  : {info.name} / {info.model}"
          + (f"  (thinking: {info.thinking})"
             if getattr(info, "thinking", "off") != "off" else ""),
          flush=True)
    if info.is_remote:
        print(
            "            remote: the brief and the generated document leave "
            "this machine",
            flush=True,
        )
    if info.context_window:
        print(f"Context   : {info.context_window} tokens", flush=True)
    print(f"Brief     : {brief}", flush=True)
    print(flush=True)

    started = time.time()
    directory: Path | None = None
    live = None
    if not args.no_write:
        directory = Path(
            args.out or Path("runs") / f"{time.strftime('%Y%m%dT%H%M%S')}-{_slug(brief)}"
        )
        if not args.no_live:
            from .live import LiveView

            live = LiveView(directory, brief, f"{info.name} / {info.model}",
                            open_browser=not args.no_open)
            provider.observe(live.call)
            print(f"Live view : {live.page}", flush=True)
            print(flush=True)
    try:
        run = Orchestrator(provider, config=config).design(
            brief, answers=answers, cancellation=cancellation, watch=live
        )
    except ConfigurationError as error:
        print(error.message)
        for key, value in error.detail.items():
            print(f"  {key}: {value}")
        return EXIT_UNDECIDED

    # What was actually sent, not what was asked for. The schema can be
    # narrowed to fit a small window, and a run whose fidelity slipped should
    # say so next to its result rather than only in the JSON.
    fidelity = provider.info.schema_fidelity
    if fidelity != "exact":
        print(
            f"\nSchema    : sent {fidelity} to fit the context window. The "
            "document is still\n            validated against the full schema "
            "when it comes back.",
            flush=True,
        )

    # The artefacts first: printing can fail -- a Windows console that cannot
    # encode a character, output piped and closed -- and the run's record
    # must not go with it.
    document_path: Path | None = None
    written: list[Path] = []
    if directory is not None:
        written = write_artifacts(run, directory)
        if live is not None:
            try:
                live.finish(run)
                written.append(live.page)
            except Exception:  # noqa: BLE001 - the page is a view, not a result
                pass
    try:
        print(run.render(verbose=args.verbose))
    except UnicodeEncodeError:
        print(run.render(verbose=args.verbose).encode(
            "ascii", "replace").decode("ascii"))

    if directory is not None:
        print()
        print(f"Artefacts : {directory}")
        for path in written:
            suffix = "   <- open this" if path.suffix == ".stl" else ""
            if path.suffix == ".stl" and _MESH_NOTES.get(str(path)):
                suffix += f"  ({_MESH_NOTES[str(path)]})"
            print(f"  {path.name}{suffix}")
        document_path = next(
            (p for p in written if p.name == "document.forgeir.json"), None
        )

    _explain_the_block(run, document_path)

    if run.state is State.AWAITING_ANSWERS:
        print()
        print("Nothing was invented to fill these gaps. Answer them and re-run:")
        print()
        print("  " + _resume_command(brief, run.questions))
        print()
        print(
            "  ...or pass --assume to proceed anyway. That records each unknown "
            "as a high-risk\n  assumption rather than guessing a value, and the "
            "result cannot be released."
        )

    print()
    print(f"Wall clock: {time.time() - started:.1f} s")
    return _exit_code(run.state)


def _explain_the_block(run: Any, document_path: Path | None) -> None:
    """Say what BLOCKED means and how to clear it, at the moment it happens.

    "blocked" arrives at the end of a run that took half an hour on a local
    model, next to a part that is geometrically fine, and it reads as a
    failure. It is not one: the design rests on a number nobody agreed to, and
    agreeing is a thing a person does, in one command. Saying so here is the
    difference between a verdict people act on and a verdict people learn to
    ignore.
    """
    if run.state is not State.BLOCKED or run.report is None:
        return
    # The wording comes from `release_status`, which writes one reason per
    # unaccepted assumption as "assumption <id> has not been accepted".
    blocking = [
        reason
        for reason in run.report.release_reasons
        if reason.startswith("assumption ")
    ]
    if not blocking:
        return
    print()
    print(
        "Blocked is not failed: the part is built and measured, and it rests "
        "on assumptions\nnobody has accepted yet."
    )
    said = _what_each_assumption_says(run)
    forces_given = _loads_the_brief_gave(run)
    for reason in blocking:
        print(f"  - {reason}")
        # The id alone reads as Forge not having heard the brief: "it still
        # asked the design load, although I said 150 N". What it assumes is
        # in the statement -- the 150 N is the brief's; that it is steady,
        # not shock or cycling, is not -- so the statement is shown with it.
        identifier = reason.split()[1] if len(reason.split()) > 1 else ""
        if said.get(identifier):
            print(f"      {said[identifier]}")
        if identifier in forces_given:
            print(f"      The {forces_given[identifier]:g} N and where it acts "
                  "are your brief's own; what accepting this agrees to is that "
                  "it is steady -- no shock, vibration or repeated cycling, "
                  "which a margin against yield does not cover.")
    if document_path is not None:
        print()
        print("Read them, and accept the ones you agree with:")
        print(f"  forge accept {document_path}")
        print(f"  forge accept {document_path} --all")


def _what_each_assumption_says(run: Any) -> dict[str, str]:
    """Each assumption's statement and value, by id, from the run's record
    and its document."""
    said: dict[str, str] = {}
    sources = [getattr(getattr(run, "requirements", None), "assumptions", ())
               or (), ((getattr(run, "document_payload", None) or {})
                       .get("assumptions") or ())]
    for source in sources:
        for assumption in source:
            if not isinstance(assumption, dict):
                assumption = getattr(assumption, "as_json", lambda: {})()
            identifier = str(assumption.get("id", ""))
            statement = str(assumption.get("statement", "")).strip()
            value = assumption.get("value")
            magnitude = value.get("magnitude") if isinstance(value, dict) \
                else None
            if isinstance(magnitude, (int, float)) and statement:
                statement += f" [{magnitude:g} {value.get('unit', '')}]".replace(
                    " ]", "]")
            if identifier and statement:
                said[identifier] = statement
    return said


def _loads_the_brief_gave(run: Any) -> dict[str, float]:
    """The load assumptions whose force the brief itself states, by id."""
    brief = str(getattr(run, "brief", "") or "").lower()
    given: dict[str, float] = {}
    sources = [getattr(getattr(run, "requirements", None), "assumptions", ())
               or (), ((getattr(run, "document_payload", None) or {})
                       .get("assumptions") or ())]
    for source in sources:
        for assumption in source:
            if not isinstance(assumption, dict):
                assumption = getattr(assumption, "as_json", lambda: {})()
            value = assumption.get("value")
            if not isinstance(value, dict) or str(value.get("unit", "")) != "N":
                continue
            magnitude = value.get("magnitude")
            if isinstance(magnitude, (int, float)) and re.search(
                    rf"(?<![\d.]){re.escape(f'{magnitude:g}')}\s*n(?![a-z])",
                    brief):
                given[str(assumption.get("id", ""))] = float(magnitude)
    return given


def _what_the_call_is(request: ModelRequest) -> str:
    """The step a model call is, as the person watching would say it: the
    failure analyst asked to look over a part that passed everything is the
    last look, not a failure -- shown as `failure_analyst`, a plate that
    released cleanly read as if something had gone wrong."""
    purpose = request.purpose or "call"
    if purpose == "failure_analyst":
        try:
            first = request.messages[0].content
        except (AttributeError, IndexError, TypeError):
            return purpose
        if "last look before the part is released" in str(first):
            return "last_look"
    return purpose


def _progress_observer():
    def observe(request: ModelRequest, response: ModelResponse) -> None:
        print(
            f"    -> {_what_the_call_is(request):22} "
            f"{response.usage.input_tokens:>6} in "
            f"{response.usage.output_tokens:>6} out  "
            f"{response.latency_seconds:>5.1f}s"
            + ("  (fixture)" if response.from_fixture else ""),
            flush=True,
        )

    return observe


def _install_interrupt_handler(cancellation: CancellationToken) -> None:
    """Ctrl-C cancels the run rather than killing the process.

    The difference matters: a cancelled run still returns, still renders, and
    still writes its artefacts, so an expensive partial run is not lost to an
    impatient keystroke.
    """

    def handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        if cancellation.cancelled:
            raise KeyboardInterrupt
        print("\n  cancelling after the current step...", flush=True)
        cancellation.cancel()

    try:
        signal.signal(signal.SIGINT, handler)
    except ValueError:  # pragma: no cover - not the main thread
        pass


# ----------------------------------------------------------------------
def add_design_parser(subparsers: Any) -> argparse.ArgumentParser:
    design = subparsers.add_parser(
        "design",
        help="turn a sentence into a verified ForgeIR document",
        description=(
            "Run the full loop: interpret the brief, derive requirements, ask "
            "about anything that would otherwise have to be invented, design, "
            "compile with bounded repair, measure and gate."
        ),
    )
    design.add_argument("brief", help='what you want, in a sentence or a paragraph')

    model = design.add_argument_group("model")
    model.add_argument(
        "--provider",
        choices=("anthropic", "ollama", "openai", "fixture"),
        default="anthropic",
        help="anthropic (default); `ollama` for a local Ollama, which is the "
             "only local transport measured to enforce the schema; `openai` "
             "for any OpenAI-compatible endpoint; or replay",
    )
    model.add_argument("--model", help="model identifier for the chosen provider")
    model.add_argument(
        "--base-url",
        help="endpoint for --provider openai or ollama. For `ollama` give the "
             "server root (http://localhost:11434), not the /v1 path",
    )
    model.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="environment variable holding the key for --provider openai",
    )
    model.add_argument(
        "--structured-mode",
        choices=("json_schema", "tools", "json_object"),
        default="json_schema",
        help="how the endpoint is asked for structured output, strongest "
        "first; `tools` suits endpoints whose function calling is better "
        "supported than their json_schema",
    )
    model.add_argument(
        "--exact-schema",
        action="store_true",
        help="send the schema exactly as --schema-dialect asks for it, and "
        "refuse a request that will not fit rather than narrowing it to make "
        "room. Maximum fidelity, and the refusal names the context length that "
        "would hold it.",
    )
    model.add_argument(
        "--schema-dialect",
        choices=("json_schema", "openapi", "opaque"),
        default="json_schema",
        help="how much of the output schema the endpoint can take. `openapi` "
        "keeps only widely-supported keywords; `opaque` also collapses unions "
        "and deep nesting, for endpoints that refuse large schemas. Whatever "
        "is dropped is recorded in the run; nothing is checked less strictly.",
    )
    model.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds to wait for one response. A small model on CPU can take "
        "several minutes to write a document; the default gives up first and "
        "then retries, which wastes the work already done.",
    )
    model.add_argument(
        "--context-window",
        type=int,
        default=None,
        help="the endpoint's context length in tokens. Given, a request that "
        "would not fit is refused before it is sent -- a local runtime "
        "truncates it silently instead, which produces a confident answer "
        "written against half the instructions.",
    )
    model.add_argument(
        "--thinking",
        choices=("auto", "adaptive", "enabled", "off"),
        default=None,
        help="how a Claude model reasons before it answers. `auto` (the "
        "default) lets each model think the way it can; `off` makes it answer "
        "at once, by a forced tool call -- cheaper, and the way every design "
        "was written before thinking was on. Also FORGE_THINKING.",
    )
    model.add_argument(
        "--effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default=None,
        help="how much a Claude model that thinks adaptively puts into each "
        "answer; its own default when not given. Also FORGE_EFFORT.",
    )
    model.add_argument("--fixtures", help="directory to replay with --provider fixture")
    model.add_argument("--record", help="record every response into this directory")

    limits = design.add_argument_group("budget")
    limits.add_argument("--max-tokens", type=int, default=600_000)
    limits.add_argument("--max-calls", type=int, default=60)
    limits.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="cap what each role reserves for its answer. The defaults assume "
        "a large context; on a local model with 16k, reserving 16,384 leaves "
        "no room for the prompt. A bracket document is about 3,000 tokens, so "
        "6144 is ample.",
    )
    limits.add_argument(
        "--max-cost", type=float, default=None, help="hard stop, estimated USD"
    )

    watching = design.add_argument_group("watching")
    watching.add_argument(
        "--no-live", action="store_true",
        help="do not write the live page (live.html) into the run's folder")
    watching.add_argument(
        "--no-open", action="store_true",
        help="write the live page but do not open it in the browser")

    loop = design.add_argument_group("loop")
    loop.add_argument("--repairs", type=int, default=3, help="compile repair attempts")
    loop.add_argument(
        "--redesigns", type=int, default=1,
        help="when repairs leave the design failing, design it again this "
        "many times, told what failed (0 turns it off)")
    loop.add_argument(
        "--gate-repairs", type=int, default=3, help="design changes to make a gate pass"
    )
    loop.add_argument(
        "--assume",
        action="store_true",
        help="do not stop to ask; record unknowns as high-risk assumptions instead",
    )
    loop.add_argument(
        "--answer",
        action="append",
        metavar="ID=TEXT",
        help="answer a question from an earlier run",
    )
    loop.add_argument("--answers", help="JSON file of {question_id: answer}")

    output = design.add_argument_group("output")
    output.add_argument("--out", help="directory for the run's artefacts")
    output.add_argument(
        "--no-write", action="store_true", help="print only; write nothing"
    )
    output.add_argument("--depth", type=int, default=8, help="octree measurement depth")
    output.add_argument("--mesh-resolution", type=int, default=96)
    output.add_argument(
        "-v", "--verbose", action="store_true", help="event log and per-call usage"
    )

    design.set_defaults(handler=command_design)
    return design


__all__ = [
    "add_design_parser",
    "command_design",
    "build_provider",
    "collect_answers",
    "write_artifacts",
    "EXIT_QUESTIONS",
]
