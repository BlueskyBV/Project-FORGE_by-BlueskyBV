"""The spec in fixed wording: what the person reads and confirms.

The model never writes this text. Every line is produced here from the typed
spec, by one template per item kind, so what the person approves is exactly
what will be built and checked (plan, section 4.2): each kind's own, in
:mod:`forge_spec.items.words`. First come the
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

from dataclasses import dataclass

from .checks import SpecReport
from .draft import Item, PartSpec
from .items.words import WORDS

# The template helpers, which the confirmation views word their notes with too.
from .items.words._common import _Line as _Line
from .items.words._common import _n as _n
from .items.words._common import _outline as _outline
from .items.words._common import _tag
from .schema import KINDS
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
    #: What the brief asks that Forge can't make yet (schema 1.10): first, it decides the part.
    unable: tuple[str, ...] = ()

    def text(self) -> str:
        out = [self.title, ""]
        if self.unable:
            out.append("Forge can't make yet:")
            out += [f"  - {u}" for u in self.unable]
            out.append("")
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


def _line(item: Item) -> str:
    line = _Line(item)
    text = WORDS[item.kind].sentence(line)
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
    unable = tuple(f"{e.what}: {_quote(brief, e.words)}" for e in spec.unable)
    return RenderedSpec(f"{spec.name} - {len(spec.items)} item(s)", assumptions, caveats,
                        tuple(lines), not_modelled, tuple(silent), answers, requirements, unable)  # fmt: skip
