"""The spec page: what the person reads before confirming, as one HTML file.

Written into the run's folder at every round of ``forge spec`` (plan, section
4.2), in the plan's order: what is still to settle and what was assumed; the
top, front and side views with every value dimensioned
(:mod:`forge_spec.render_views`); the brief with each word coloured by the
item it fed and every word nothing uses marked; and the fixed wording of the
spec. It opens from disk with no server, and stays as the run's record.

The page can't confirm anything. Confirming takes the code Forge shows only
in its own window, typed back there (rule R12), so no program that drives a
browser can confirm a spec by reading this page.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path

from forge_spec import NumberedBrief
from forge_spec.checks import SpecReport, item_words
from forge_spec.questions import Question
from forge_spec.render import render
from forge_spec.render_views import render_views

__all__ = ["spec_page", "write_spec_page"]

#: One colour per item, in the order the items are listed; chosen to read on
#: light and dark backgrounds alike.
_PALETTE = (
    "#2e7dd7",
    "#d9822b",
    "#2f9e66",
    "#b44fc4",
    "#c9a227",
    "#d0455a",
    "#159aa5",
    "#7a6cf0",
)

#: The material's words: a requirement, not an item.
_MATERIAL = "#8a8f98"

_STYLE = """
:root { --ink: #1b1d21; --muted: #5c6370; --paper: #ffffff; --panel: #f4f5f7; --line: #d9dce1;
        --warn: #c0392b; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e6e8eb; --muted: #9aa1ab; --paper: #15171a; --panel: #1f2226; --line: #33373d;
          --warn: #ff6b5b; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
       font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; color: var(--muted); text-transform: uppercase;
     letter-spacing: .04em; }
.status { margin: 0; color: var(--muted); }
.brief { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem; padding: 1rem;
         white-space: pre-wrap; overflow-wrap: anywhere; }
.w { border-bottom: 3px solid var(--c); padding: 0 .05em; }
.left-out { color: var(--muted); text-decoration: line-through; }
.silent { color: var(--muted); font-style: italic; }
.unused { outline: 2px solid var(--warn); outline-offset: 1px; border-radius: .2em; }
.answer { background: color-mix(in srgb, var(--panel) 60%, #2e7dd7 40%); border-radius: .2em; }
.legend { display: flex; flex-wrap: wrap; gap: .5rem 1rem; list-style: none; padding: 0; margin: .5rem 0 0;
          color: var(--muted); font-size: .9rem; }
.legend li::before { content: ""; display: inline-block; width: .8em; height: .8em; margin-right: .35em;
                     border-radius: .15em; background: var(--c); vertical-align: -.05em; }
ol, ul { padding-left: 1.4rem; }
li { margin: .3rem 0; }
.q { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem; padding: .75rem 1rem;
     margin: .5rem 0; }
.q p { margin: 0 0 .25rem; }
.q .kind { color: var(--muted); font-size: .85rem; text-transform: uppercase; letter-spacing: .04em; }
.tag { color: var(--muted); font-size: .85rem; }
.views { display: flex; flex-wrap: wrap; align-items: flex-start; gap: .75rem; }
.views figure { --halo: var(--panel); margin: 0; max-width: 100%; overflow-x: auto; background: var(--panel);
                border: 1px solid var(--line); border-radius: .5rem; padding: .5rem .75rem; color: var(--ink); }
.views figcaption { color: var(--muted); font-size: .85rem; margin-bottom: .25rem; }
.views svg { display: block; }  /* never shrunk: every view keeps the one scale; a wide one scrolls */
footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); }
"""


def spec_page(report: SpecReport, brief: NumberedBrief, *, status: str,
              round_: Sequence[Question] = ()) -> str:  # fmt: skip
    """The page, as one self-contained HTML document."""
    e = html.escape
    rendered = render(report, brief)
    spec = report.spec
    colours: dict[int, list[tuple[str, str]]] = {}
    legend: list[tuple[str, str]] = []
    if spec is not None:
        for n, item in enumerate(spec.items):
            colour = _PALETTE[n % len(_PALETTE)]
            legend.append((item.id, colour))
            for i in item_words(item):
                colours.setdefault(i, []).append((item.id, colour))
    material = spec.requirements.material if spec else None
    if material is not None:
        legend.append(("material", _MATERIAL))
        for i in material.provenance.words:
            colours.setdefault(i, []).append(("the material", _MATERIAL))
    left_out = {i for entry in (spec.not_modelled if spec else ()) for i in entry.words}
    left_out |= {i for beyond in (spec.unable if spec else ()) for i in beyond.words}
    silent = {i for entry in (spec.silent if spec else ()) for s in brief.sentences
              if s.index == entry.sentence for i in s.words}  # fmt: skip
    accounting = report.accounting
    unused = (
        {w.index for w in (*accounting.uncited_numbers, *accounting.uncited_words)}
        if accounting
        else set()
    )
    answered = {i for s in brief.answers for i in s.words}

    pieces: list[str] = []
    at = 0
    for word in brief.words:
        pieces.append(e(brief.text[at : word.start]))
        text = e(brief.text[word.start : word.end])
        classes, style, said = [], "", []
        if word.index in colours:
            classes.append("w")
            style = f' style="--c: {colours[word.index][0][1]}"'
            said.append("fed " + ", ".join(name for name, _ in colours[word.index]))
        if word.index in left_out:
            classes.append("left-out")
            said.append("not modelled")
        if word.index in silent:
            classes.append("silent")
            said.append("says nothing about the shape")
        if word.index in unused:
            classes.append("unused")
            said.append("nothing in the spec uses it")
        if word.index in answered:
            classes.append("answer")
            said.append("your answer")
        if classes:
            pieces.append(
                f'<span class="{" ".join(classes)}"{style} title="{e("; ".join(said))}">{text}</span>'
            )
        else:
            pieces.append(text)
        at = word.end
    pieces.append(e(brief.text[at:]))

    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{e(spec.name if spec else 'spec')} - Forge</title>", f"<style>{_STYLE}</style>", "</head>",
           "<body><main>", f"<h1>{e(spec.name if spec else 'No spec')}</h1>", f'<p class="status">{e(status)}</p>']  # fmt: skip
    if round_:
        out.append("<h2>To settle</h2>")
        for q in round_:
            options = "".join(f"<li>{e(o.label)}</li>" for o in q.options)
            out.append(f'<div class="q"><p class="kind">{e(q.id)} &middot; {e(q.kind)}</p><p>{e(q.text)}</p>'
                       f"<ol>{options}</ol></div>")  # fmt: skip
    # Assumptions still to settle are listed above, with their answers; any
    # others are ones the person has already seen and kept.
    settling = {q.text for q in round_ if q.kind == "assumption"}
    assumed = tuple(a for a in rendered.assumptions if a not in settling)
    assumed_title = "Kept by you" if settling else "Assumed (check these first)"
    for title, entries in (("Your answers", rendered.answers), (assumed_title, assumed),
                           ("Worth a second look", rendered.caveats)):  # fmt: skip
        if entries:
            out.append(
                f"<h2>{e(title)}</h2><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in entries)
                + "</ul>"
            )
    out += _views(report)
    out += ["<h2>Your brief</h2>", f'<div class="brief">{"".join(pieces)}</div>']
    if legend:
        out.append(
            '<ul class="legend">'
            + "".join(f'<li style="--c: {c}">{e(n)}</li>' for n, c in legend)
            + "</ul>"
        )
    if rendered.requirements:
        out.append(
            "<h2>Requirements</h2><ul>"
            + "".join(f"<li>{e(x)}</li>" for x in rendered.requirements)
            + "</ul>"
        )
    out.append("<h2>The spec</h2><ol>")
    for line in rendered.lines:
        body, _, tag = line.rpartition("  [")
        shown = f'{e(body)} <span class="tag">[{e(tag)}</span>' if body else e(line)
        out.append(f"<li>{shown}</li>")
    out.append("</ol>")
    for title, entries in (("Forge can't make yet", rendered.unable), ("Not modelled", rendered.not_modelled),
                           ("Taken to say nothing about the shape", rendered.silent)):  # fmt: skip
        if entries:
            out.append(
                f"<h2>{e(title)}</h2><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in entries)
                + "</ul>"
            )
    out.append("<footer>Answer and confirm in Forge's own window: confirming takes the code shown only "
               "there. This page can't confirm anything.</footer>")  # fmt: skip
    out.append("</main></body></html>")
    return "\n".join(out)


def _views(report: SpecReport) -> list[str]:
    """The top, front and side views, what they give in words, and what they couldn't draw."""
    e = html.escape
    views = render_views(report)
    out: list[str] = []
    drawn = [v for v in views.views if v.svg]
    if drawn:
        out.append("<h2>Views</h2>")
        out.append('<div class="views">' + "".join(f"<figure><figcaption>{e(v.caption)}</figcaption>{v.svg}</figure>"
                                                   for v in drawn) + "</div>")  # fmt: skip
        out.append('<p class="tag">Sizes in mm unless a unit is given. Hidden edges dashed, centre lines '
                   "dash-dot.</p>")  # fmt: skip
    if views.words:
        out.append(
            "<h2>Shown in words</h2><ul>"
            + "".join(f"<li>{e(d.text)}</li>" for d in views.words)
            + "</ul>"
        )
    if views.not_drawn:
        out.append(
            "<h2>Not drawn</h2><ul>"
            + "".join(
                f"<li>{e(i)}: not placed, so not drawn</li>" for i in views.not_drawn
            )
            + "</ul>"
        )
    return out


def write_spec_page(directory: Path, report: SpecReport, brief: NumberedBrief, *, status: str,
                    round_: Sequence[Question] = ()) -> Path | None:  # fmt: skip
    """Write ``spec.html`` into the run's folder; a page that can't be written never stops a run."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        page = directory / "spec.html"
        page.write_text(
            spec_page(report, brief, status=status, round_=round_), encoding="utf-8"
        )
    except OSError:
        return None
    return page
