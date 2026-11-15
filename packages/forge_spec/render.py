"""The spec in fixed wording: what the person reads and confirms.

The model never writes this text. Every line is produced here from the typed
spec, by one template per item kind, so what the person approves is exactly
what will be built and checked (plan, section 4.2). First come the
assumptions, then caveats (readings worth a second look), then one numbered
line per item, each tagged with how it will be verified (exact, bounded or
constrained), then what the spec leaves out: the words not modelled and the
sentences taken to say nothing about the shape, each with its reason.

Every field of every item is worded: a template that left one out would let
the person confirm something they never saw, so a field a template doesn't
word is added at the end of its line, and a test fails until the template
words it. Every number carries its unit, its tolerance, and the source of
anything not read from the brief: ``(assumed)``, ``(= 40 mm - 5 mm)``,
``(ISO 273 normal clearance for M4)``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .checks import SpecReport
from .draft import (
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    FieldValue,
    Fit,
    Item,
    On,
    PartSpec,
    Place,
    Profile,
    Text,
    Through,
)
from .schema import KINDS
from .tables import TAPPED, lookup_fit, metric_size
from .values import Count, Provenance, Source, Value
from .words import NumberedBrief

__all__ = ["RenderedSpec", "render"]


@dataclass(frozen=True)
class RenderedSpec:
    title: str
    assumptions: tuple[str, ...]
    caveats: tuple[str, ...]
    lines: tuple[str, ...]
    not_modelled: tuple[str, ...] = ()
    silent: tuple[str, ...] = ()
    #: What the person answered: sentences added to the brief, which values cite.
    answers: tuple[str, ...] = ()
    #: What the part must be beyond its shape: "Material: 'PETG'".
    requirements: tuple[str, ...] = ()

    def text(self) -> str:
        out = [self.title, ""]
        if self.requirements:
            out += [*self.requirements, ""]
        if self.answers:
            out.append("Your answers:")
            out += [f"  - {a}" for a in self.answers]
            out.append("")
        if self.assumptions:
            out.append("Assumed (check these first):")
            out += [f"  - {a}" for a in self.assumptions]
            out.append("")
        if self.caveats:
            out.append("Worth a second look:")
            out += [f"  - {c}" for c in self.caveats]
            out.append("")
        out += [f"{n}. {line}" for n, line in enumerate(self.lines, start=1)]
        if self.not_modelled:
            out += ["", "Not modelled:"] + [f"  - {x}" for x in self.not_modelled]
        if self.silent:
            out += ["", "Taken to say nothing about the shape:"] + [
                f"  - {x}" for x in self.silent
            ]
        return "\n".join(out)


def _n(x: float) -> str:
    """A number as the shortest text that reads back as exactly it.

    Two values that differ never print alike, so the person confirms what
    the spec holds, not a rounding of it.
    """
    if x == 0:
        return "0"
    text = repr(float(x))
    return text[:-2] if text.endswith(".0") else text


def _tag(p: Provenance) -> str:
    if p.source is Source.ASSUMED:
        return " (assumed)"
    if p.source is Source.TABLE:
        return f" (table {p.table})"
    if p.source is Source.DERIVED:
        return f" (= {p.formula})"
    return ""


def _v(value: object) -> str:
    """A value with its unit, tolerance and source."""
    if isinstance(value, Count):
        return f"{value.n}{_tag(value.provenance)}"
    if not isinstance(value, Value):
        return "?"
    text = f"{_n(value.nominal)} {value.unit}"
    if value.tolerance is not None:
        text += f" +{_n(value.tolerance.plus)}/-{_n(value.tolerance.minus)}"
    return text + _tag(value.provenance)


def _c(value: object) -> str:
    """A choice, with its source."""
    if isinstance(value, Choice):
        return f"{value.value.upper() if len(value.value) == 1 else value.value}{_tag(value.provenance)}"
    return "?"


def _axis(axis: str, position: AxisPosition, pattern: str | None = None) -> str:
    """A position along one axis, said as the solver measures it (docs/definitions/place.md).

    From an edge, a row, grid or rectangle of copies is measured to its
    nearest copy, a circle of them to its centre.
    """
    if position.mode == "centred":
        return f"centred along {axis.upper()}" + (
            _tag(position.provenance) if position.provenance else ""
        )
    distance = _v(position.distance)
    if position.mode == "offset":
        return f"offset {distance} along {axis.upper()} from the centre"
    whose = "its" if pattern is None else "the nearest one's"
    to = f"{whose} centre" if position.to == "centre" else f"{whose} near edge"
    if pattern in ("circle", "arc"):
        to = "the circle's centre"
    return f"{distance} from the {position.side} edge to {to}" + (
        "" if position.to_given else " (assumed)"
    )


def _place(place: Place | None) -> str:
    if place is None:
        return "where the solver puts it (see the assumptions)"
    kind = place.pattern.kind if place.pattern is not None else None
    parts = [_axis(axis, pos, kind) for axis, pos in sorted(place.axes.items())]
    if place.angle is not None:
        parts.append(f"at {_v(place.angle)} around the axis")
    pattern = place.pattern
    if pattern is not None:
        v, n = pattern.values, pattern.counts
        axis = (pattern.axis or "?").upper() + (
            _tag(pattern.axis_provenance) if pattern.axis_provenance else ""
        )

        def named(prefix: str) -> str:
            keys = sorted(
                k for k in set(v) | set(n) if k.startswith(prefix) and k != "each"
            )
            return ", ".join(
                f"{k[len(prefix) :].upper()} {_v(v[k] if k in v else n[k])}"
                for k in keys
            )

        if pattern.kind == "corners":
            parts.append(
                f"one at each corner, centres in from the edges by {named('inset_')}"
            )
        elif pattern.kind == "rectangle":
            parts.append(f"at the corners of a rectangle {named('')}")
        elif pattern.kind == "ends":
            parts.append(
                f"one near each end along {axis}, centres {_v(v.get('inset'))} in from the ends"
            )
        elif pattern.kind == "row":
            parts.append(
                f"{_v(n.get('count'))} in a row along {axis}, {_v(v.get('pitch'))} apart"
            )
        elif pattern.kind == "grid":
            parts.append(f"a grid: counts {named('count_')}; pitches {named('pitch_')}")
        elif pattern.kind in ("circle", "arc"):
            if "diameter" in v:
                where = f" on a {_v(v['diameter'])} circle"
                start = _v(v["start"]) if "start" in v else "0 deg (assumed)"
            elif (
                "start" in v
            ):  # on a round side the circle is the side; or the spec is faulty
                where, start = " round the axis, with no circle size", _v(v["start"])
            else:
                where, start = " round the side", "the angle above"
            if pattern.kind == "circle":
                spacing = "equally spaced"
            else:
                spacing = f"{_v(v.get('step'))} apart"
            parts.append(f"{_v(n.get('count'))} {spacing}{where}, the first at {start}")
        if "each" in n:
            parts.append(f"{_v(n['each'])} at each position")
    if place.concentric:
        parts.append(f"concentric with {place.concentric}" + (
            _tag(place.concentric_provenance) if place.concentric_provenance else ""))  # fmt: skip
    return ", ".join(parts) if parts else "with no position given (see the assumptions)"


def _depth(value: object) -> str:
    if isinstance(value, Through):
        return "right through" + _tag(value.provenance)
    return f"{_v(value)} deep"


def _diameter(value: object) -> str:
    if isinstance(value, Fit):
        entry = lookup_fit(value.fit, value.for_, value.grade or "normal")
        size = (
            f"{_n(entry.size_mm)} mm ({entry.source})"
            if entry
            else f"? ({value.fit} for {value.for_})"
        )
        return f"Ø{size}" + _tag(value.provenance)
    return f"Ø{_v(value)}"


def _text(value: object) -> str:
    return f"{value.text!r}{_tag(value.provenance)}" if isinstance(value, Text) else "?"


def _thread(value: object) -> str:
    """A thread with its pitch said outright, so "M8x40" can't pass for an M8 bolt 40 long."""
    if not isinstance(value, Text):
        return "?"
    size = metric_size(value.text)
    coarse = TAPPED.get(size[0], (None, None))[0] if size else None
    if size is None or (size[1] is None and coarse is None):
        return _text(value)
    pitch = size[1] if size[1] is not None else coarse
    series = "coarse" if size[1] is None or pitch == coarse else "fine"
    return (
        f"{value.text!r} ({series}, {_n(pitch or 0)} mm pitch){_tag(value.provenance)}"
    )


def _point(p: tuple[float, float]) -> str:
    return f"({_n(p[0])}, {_n(p[1])})"


def _outline(profile: Profile) -> str:
    steps = []
    for seg in profile.segments:
        if seg.centre is None:
            steps.append(f"line to {_point(seg.to)}")
        else:
            turn = "clockwise" if seg.clockwise else "anticlockwise"
            steps.append(f"arc {turn} to {_point(seg.to)} about {_point(seg.centre)}")
    return f"the outline (mm) from {_point(profile.start)}: {', '.join(steps)}" + _tag(
        profile.provenance
    )


def _generic(value: FieldValue) -> str:
    if isinstance(value, (Value, Count)):
        return _v(value)
    if isinstance(value, Choice):
        return _c(value)
    if isinstance(value, Text):
        return _text(value)
    if isinstance(value, Faces):
        return (", ".join(value.faces) or "none") + _tag(value.provenance)
    if isinstance(value, Profile):
        return _outline(value)
    return str(value)


@dataclass
class _Line:
    """One item's line, built from fields that are each worded once."""

    item: Item
    used: set[str] = field(default_factory=set)

    def get(self, name: str) -> FieldValue | None:
        self.used.add(name)
        return self.item.get(name)

    def v(self, name: str) -> str:
        return _v(self.get(name))

    def rest(self) -> str:
        left = [n for n in self.item.fields if n not in self.used]
        return "".join(f"; {n} {_generic(self.item.fields[n])}" for n in left)


def _where(line: _Line, *, cut: bool = False) -> str:
    on = line.get("on")
    place = line.get("place")
    if not isinstance(on, On):
        return "at the origin"
    verb = "into" if cut else "on"
    return f"{verb} the {on.face} face of {on.item}, {_place(place if isinstance(place, Place) else None)}"


def _count(line: _Line) -> str:
    count = line.get("count")
    return f"{_v(count)} x " if isinstance(count, Count) else ""


def _axis_of(line: _Line) -> str:
    axis = line.get("axis")
    if isinstance(axis, Choice):
        return f", axis {_c(axis)}"
    return "" if isinstance(line.item.get("on"), On) else ", axis Z (assumed)"


def _edges(value: object) -> str:
    if not isinstance(value, EdgeSet):
        return "?"
    if value.which == "joint":
        return f"the edges where {value.of} meets {value.where_meets}"
    return f"the {value.which} edges of {value.of}"


_Template = Callable[[_Line], str]


def _mode(value: object) -> str:
    if not isinstance(value, Choice):
        return "?"
    word = {"engrave": "engraved", "emboss": "embossed"}.get(value.value, value.value)
    return word + _tag(value.provenance)


def _sphere(line: _Line) -> str:
    portion = line.get("portion")
    head = f"{line.item.id} ({_c(portion)}): Ø{line.v('diameter')}, "
    if isinstance(portion, Choice) and portion.value == "upper_half":
        return "Dome (upper half of a ball, flat side down) " + head + _where(line)
    on = line.get("on")
    if not isinstance(on, On):
        return "Ball " + head + "resting on the origin (its lowest point there)"
    place = line.get("place")
    return ("Ball " + head + f"its centre on the {on.face} face of {on.item} (half sunk into it), "
            + _place(place if isinstance(place, Place) else None))  # fmt: skip


def _hole(line: _Line) -> str:
    extras = []
    bore, sink = line.get("counterbore"), line.get("countersink")
    if isinstance(bore, Counterbore):
        extras.append(f"counterbored Ø{_v(bore.diameter)}, {_v(bore.depth)} deep")
    if isinstance(sink, Countersink):
        extras.append(f"countersunk to Ø{_v(sink.diameter)} at {_v(sink.angle)}")
    extra = "".join(f", {e}" for e in extras)
    return (f"{_count(line)}hole {line.item.id}: {_diameter(line.get('diameter'))}{extra}, "
            f"{_depth(line.get('depth'))}, {_where(line, cut=True)}")  # fmt: skip


def _pocket(line: _Line) -> str:
    if line.item.get("shape") is not None and _c(line.item.get("shape")).startswith(
        "circle"
    ):
        shape = f"round pocket {line.item.id} ({_c(line.get('shape'))}): Ø{line.v('diameter')}"
    else:
        corners = (
            f", corners R{line.v('corner_radius')}"
            if line.item.get("corner_radius")
            else ""
        )
        shape = (f"rectangular pocket {line.item.id} ({_c(line.get('shape'))}): {line.v('length')} x "
                 f"{line.v('width')}{corners}")  # fmt: skip
    return (
        f"{_count(line)}{shape}, {_depth(line.get('depth'))}, {_where(line, cut=True)}"
    )


def _shell(line: _Line) -> str:
    opened = line.get("open")
    faces = _generic(opened) if isinstance(opened, Faces) else "?"
    sealed = isinstance(opened, Faces) and not opened.faces
    several = isinstance(opened, Faces) and len(opened.faces) > 1
    opposite = (
        "the walls opposite the openings"
        if several
        else "the wall opposite the opening"
    )
    floor = f", {opposite} {line.v('floor')}" if line.item.get("floor") else ""
    return (f"Hollow {line.get('of')} ({line.item.id}): walls {line.v('thickness')}{floor}, "
            + (f"sealed all round{_tag(opened.provenance)}" if sealed and isinstance(opened, Faces)
               else f"open at {faces}"))  # fmt: skip


_TEMPLATES: dict[str, _Template] = {
    "block": lambda ln: (f"Block {ln.item.id}: {ln.v('length')} x {ln.v('width')} x {ln.v('height')} "
                         f"(length x width x height), {_where(ln)}"),
    "cylinder": lambda ln: (f"Cylinder {ln.item.id}: Ø{ln.v('diameter')}, {ln.v('length')} long"
                            f"{_axis_of(ln)}, {_where(ln)}"),
    "tube": lambda ln: (f"Tube {ln.item.id}: Ø{ln.v('outer_diameter')} outside, Ø{ln.v('inner_diameter')} "
                        f"bore right through, {ln.v('length')} long{_axis_of(ln)}, {_where(ln)}"),
    "sphere": _sphere,
    "cone": lambda ln: (f"Cone {ln.item.id}: Ø{ln.v('base_diameter')} at the base to Ø{ln.v('top_diameter')} "
                        f"at the top, {ln.v('length')} long{_axis_of(ln)}, {_where(ln)}"),
    "extrusion": lambda ln: (f"Extrusion {ln.item.id}: {_generic(ln.get('profile'))}, pushed {ln.v('length')}"  # type: ignore[arg-type]
                             f"{_axis_of(ln)}, {_where(ln)}"),
    "revolution": lambda ln: (f"Revolution {ln.item.id}: {_generic(ln.get('profile'))}, turned about its axis"  # type: ignore[arg-type]
                              f"{_axis_of(ln)}, {_where(ln)}"),
    "hole": _hole,
    "slot": lambda ln: (f"{_count(ln)}slot {ln.item.id}: {ln.v('width')} wide, {ln.v('length')} long end to end, "
                        f"along {_c(ln.get('along'))}, {_c(ln.get('ends'))} ends, {_depth(ln.get('depth'))}, "
                        f"{_where(ln, cut=True)}"),
    "pocket": _pocket,
    "boss": lambda ln: f"{_count(ln)}boss {ln.item.id}: Ø{ln.v('diameter')}, {ln.v('height')} tall, {_where(ln)}",
    "post": lambda ln: (f"{_count(ln)}post {ln.item.id}: {ln.v('length')} x {ln.v('width')}, {ln.v('height')} tall, "
                        f"{_where(ln)}"),
    "tab": lambda ln: (f"{_count(ln)}tab {ln.item.id}: sticking out {ln.v('length')}, {ln.v('width')} wide, "
                       f"{ln.v('thickness')} thick along {_c(ln.get('thickness_along'))}, {_c(ln.get('end'))} end, "
                       f"{_where(ln)}"),
    "rib": lambda ln: (f"{_count(ln)}rib {ln.item.id}: {ln.v('length')} long along {_c(ln.get('along'))}, "
                       f"{ln.v('thickness')} thick, {ln.v('height')} tall, {_where(ln)}"),
    "fillet": lambda ln: f"Round {_edges(ln.get('edges'))} to R{ln.v('radius')} ({ln.item.id})",
    "chamfer": lambda ln: f"Chamfer {_edges(ln.get('edges'))} by {ln.v('size')} ({ln.item.id})",
    "shell": _shell,
    "text": lambda ln: (f"Text {ln.item.id}: {_text(ln.get('text'))} {_mode(ln.get('mode'))} {ln.v('depth')}, "
                        f"capitals {ln.v('height')} tall, {_where(ln)}"),
    "thread": lambda ln: (f"Thread {ln.item.id}: {_thread(ln.get('designation'))}, {_c(ln.get('hand'))}-handed, "
                          f"on {ln.get('of')}"
                          + (f", {ln.v('length')} from the free end" if ln.item.get("length") else ", full length")),
    "region": lambda ln: (f"Freeform region {ln.item.id} within {ln.v('length')} x {ln.v('width')} x {ln.v('height')}"
                          + (f", no wall under {ln.v('min_wall')}" if ln.item.get("min_wall") else "")
                          + f", for {_text(ln.get('describe'))}, {_where(ln)} (checked by its constraints only)"),
}  # fmt: skip


def _line(item: Item) -> str:
    line = _Line(item)
    text = _TEMPLATES[item.kind](line)
    text += line.rest()
    return text[0].upper() + text[1:]


def _quote(brief: NumberedBrief, words: tuple[int, ...]) -> str:
    try:
        return repr(brief.quote(words))
    except LookupError:
        return f"words {list(words)}"


def render(report: SpecReport, brief: NumberedBrief, *,
           include_classes: bool = True) -> RenderedSpec:  # fmt: skip
    """The fixed-wording view of a checked spec, for the person to confirm.

    What the spec leaves out is quoted from the brief, so the person reads
    the words themselves rather than word numbers.
    """
    spec: PartSpec | None = report.spec
    if spec is None:
        return RenderedSpec("(no spec)", (), (), ())
    lines = []
    for item in spec.items:
        line = _line(item)
        if include_classes:
            line += f"  [{KINDS[item.kind].verification}]"
        lines.append(line)
    assumptions = tuple(a.message for a in report.assumptions)
    caveats = tuple(c.message for c in report.caveats)
    not_modelled = tuple(
        f"{_quote(brief, e.words)}: {e.reason!r}" for e in spec.not_modelled
    )
    silent = []
    for entry in spec.silent:
        said = f"sentence {entry.sentence}"
        if 0 <= entry.sentence < len(brief.sentences):
            said = repr(brief.sentence_text(brief.sentences[entry.sentence]))
        silent.append(f"{said}: {entry.reason!r}")
    answers = tuple(repr(brief.sentence_text(s)) for s in brief.answers)
    material = spec.requirements.material
    requirements = (
        (f"Material: {material.text!r}{_tag(material.provenance)}",)
        if material is not None
        else ()
    )
    return RenderedSpec(f"{spec.name} - {len(spec.items)} item(s)", assumptions, caveats,
                        tuple(lines), not_modelled, tuple(silent), answers, requirements)  # fmt: skip
