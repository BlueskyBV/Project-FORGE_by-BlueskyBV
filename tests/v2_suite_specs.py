"""V1's validation suite (validation/SUITE.md) drafted as V2 specs by hand, citing each brief's words (docs/V2-stage4.md, 14.2).

Each brief is drafted as the spec writer's guide says (forge_spec.guide):
every value from the brief's words, cited, or assumed with its reason; every
number and sentence used, left out with why, or silent. What the schema
can't say yet (a load, a mass limit), the draft lists as not modelled; a
brief the schema can't draft at all, or that V1 expected to be turned back,
is in :data:`UNDRAFTED` with the reason.

The briefs and V1's expectations (its envelope, volume and open holes,
measured independently) are read from validation/SUITE.md itself, so the
drafts are of the very text the suite gives. The blind sets are never read
(rule: no test tunes on them).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from forge_spec import NumberedBrief
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said, span

SUITE = Path(__file__).resolve().parent.parent / "validation" / "SUITE.md"

Draft = dict[str, Any]


@dataclass(frozen=True)
class SuitePart:
    """One brief of the suite: its id and title, what V1 expected of it, the brief, and the part's expected envelope (sorted, mm), volume (mm3) and open holes, where the suite gives them."""

    id: str
    title: str
    expect: str
    brief: str
    envelope: tuple[float, float, float] | None
    volume: tuple[float, float] | None
    open_holes: int | None
    note: str


_ENTRY = re.compile(
    r"\*\*(?P<id>[A-Z]\d\d) — (?P<title>[^*]+)\*\* · expect `(?P<expect>\w+)`\n"
    r"> (?P<brief>.+)\nExpected: (?P<expected>.+)"
)


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


@cache
def suite() -> dict[str, SuitePart]:
    """Every brief of validation/SUITE.md, by id, in order."""
    found: dict[str, SuitePart] = {}
    for m in _ENTRY.finditer(SUITE.read_text(encoding="utf-8")):
        expected = m["expected"]
        envelope = volume = None
        holes: int | None = None
        e = re.search(r"envelope \[([^\]]+)\]", expected)
        if e:
            sides = _numbers(e[1])
            envelope = (sides[0], sides[1], sides[2])
        v = re.search(r"volume ([\d.]+)(?:\u2013([\d.]+))? mm", expected)
        if v:
            volume = (float(v[1]), float(v[2] or v[1]))
        h = re.search(r"open holes (\d+)", expected)
        if h:
            holes = int(h[1])
        found[m["id"]] = SuitePart(m["id"], m["title"].strip(), m["expect"], m["brief"].strip(), envelope, volume,
                                   holes, expected)  # fmt: skip
    return found


# ----------------------------------------------------------------------
# Helpers for the drafts
# ----------------------------------------------------------------------
def quiet(b: NumberedBrief, phrase: str, reason: str) -> dict[str, Any]:
    """A sentence that says nothing of the shape: the one with ``phrase`` in it."""
    return {"sentence": b.word(cite(b, phrase)[0]).sentence, "reason": reason}


def no_load(b: NumberedBrief) -> dict[str, Any]:
    return quiet(b, "load case", "it says there is no load case")


def left_out(b: NumberedBrief, text: str, reason: str) -> dict[str, Any]:
    """What the brief says that the part won't have: the words of ``text``, as written."""
    return {"words": span(b, text), "reason": reason}


def through(b: NumberedBrief, phrase: str) -> dict[str, Any]:
    return {"through": True, "from": said(b, phrase)}


def at(b: NumberedBrief, phrase: str) -> dict[str, Any]:
    """Centred along an axis, as the brief says."""
    return {"centred": said(b, phrase)}


def middle(reason: str) -> dict[str, Any]:
    return {"centred": assumed(reason)}


def item(id_: str, kind: str, words: list[int], **fields: Any) -> dict[str, Any]:
    return {"id": id_, "kind": kind, "words": words, **fields}


def on(host: str, face: str) -> dict[str, str]:
    return {"item": host, "face": face}


def formula(
    value: float, text: str, words: list[int], unit: str = "mm"
) -> dict[str, Any]:
    return {"value": value, "unit": unit, "from": {"formula": text, "words": words}}


#: Each drafted brief's draft, from its numbered words.
DRAFTS: dict[str, Callable[[NumberedBrief], Draft]] = {}
#: Each brief not drafted, and why.
UNDRAFTED: dict[str, str] = {}
#: The drafted briefs V1 had to turn back as impossible: each ends CAN'T at the spec checks, for this reason.
CANT: dict[str, str] = {"X06": "is larger than the face it is on"}


def drafts(
    id_: str,
) -> Callable[[Callable[[NumberedBrief], Draft]], Callable[[NumberedBrief], Draft]]:
    def register(
        f: Callable[[NumberedBrief], Draft],
    ) -> Callable[[NumberedBrief], Draft]:
        DRAFTS[id_] = f
        return f

    return register


# ----------------------------------------------------------------------
# R: the prompts that built V1
# ----------------------------------------------------------------------
@drafts("R01")
def _r01(b: NumberedBrief) -> Draft:
    return _spacer(b, {"length": mm(b, 40, "40 mm"), "width": mm(b, 25, "25 mm"), "height": mm(b, 5, "5 mm thick")},
                   {"diameter": mm(b, 10, "10 mm diameter"), "height": mm(b, 8, "8 mm tall")}, 1.5, 4, (3, 30),
                   "It must weigh no more than 10 g")  # fmt: skip


@drafts("R02")
def _r02(b: NumberedBrief) -> Draft:
    return draft("shaft collar", [
        item("collar", "tube", cite(b, "shaft collar"), outer_diameter=mm(b, 30, "30 mm"),
             inner_diameter=mm(b, 16, "16 mm bore"), length=mm(b, 12, "12 mm long"),
             axis=choose("z", assumed("a collar is drawn standing up"))),
        item("set_screw", "hole", cite(b, "set screw hole"), on=on("collar", "side"), diameter=mm(b, 5, "5 mm"),
             depth=through(b, "through the wall from the outside into the bore"), count=count(b, 1, "One"),
             place={"z": at(b, "halfway along the length"),
                    "angle": assumed("which way round the screw faces doesn't matter", 0, "deg")}),
    ], material=made_of(b, "stainless steel"), silent=[no_load(b)])  # fmt: skip


@drafts("R03")
def _r03(b: NumberedBrief) -> Draft:
    return draft("flange disc", [
        item("disc", "cylinder", cite(b, "flange disc"), diameter=mm(b, 60, "60 mm across"),
             length=mm(b, 8, "8 mm thick"), axis=choose("z", assumed("a disc lies flat"))),
        item("bore", "hole", cite(b, "bore"), on=on("disc", "+end"), diameter=mm(b, 20, "20 mm"),
             depth=through(b, "all the way through the centre"),
             place={"x": at(b, "the centre"), "y": at(b, "the centre")}),
        item("bolts", "hole", cite(b, "bolt holes"), on=on("disc", "+end"), diameter=mm(b, 6, "6 mm"),
             depth=through(b, "all the way through the disc"), count=count(b, 2, "Two"),
             place={"x": middle("the pair is centred on the disc"), "y": middle("the pair is centred on the disc"),
                    "pattern": {"row": {"axis": choose("x", assumed("which way across the disc doesn't matter")),
                                        "pitch": mm(b, 40, "40 mm apart"), "count": count(b, 2, "Two")}}}),
    ], material=made_of(b, "steel"), silent=[no_load(b)])  # fmt: skip


@drafts("R04")
def _r04(b: NumberedBrief) -> Draft:
    return draft("washer", [
        item("washer", "tube", cite(b, "washer"), outer_diameter=mm(b, 24, "outside diameter is 24 mm"),
             inner_diameter=mm(b, 10.5, "10.5 mm hole"), length=mm(b, 2, "2 mm thick"),
             axis=choose("z", assumed("a washer lies flat"))),
    ], material=made_of(b, "stainless steel"), silent=[no_load(b)])  # fmt: skip


def _plate_of_four(b: NumberedBrief, name: str, plate: dict[str, Any], hole: dict[str, Any],
                   material: dict[str, Any] | None, **rest: Any) -> Draft:  # fmt: skip
    """A plate with four holes on a rectangle, the suite's part asked many ways (R05, V01 to V11)."""
    return draft(name, [item("plate", "block", **plate), item("holes", "hole", on=on("plate", "+z"), **hole)],
                 material=material, **rest)  # fmt: skip


@drafts("R05")
def _r05(b: NumberedBrief) -> Draft:
    return _plate_of_four(b, "mounting plate",
        {"words": cite(b, "mounting plate"), "length": mm(b, 70, "70 mm long"), "width": mm(b, 50, "50 mm wide"),
         "height": mm(b, 4, "4 mm thick")},
        {"words": cite(b, "holes"), "diameter": mm(b, 4, "4 mm holes"), "depth": through(b, "pass through the plate"),
         "count": count(b, 4, "Four"),
         "place": {"x": middle("the rectangle is centred on the plate"),
                   "y": middle("the rectangle is centred on the plate"),
                   "pattern": {"rectangle": {"x": mm(b, 56, "56 mm"), "y": mm(b, 36, "36 mm"),
                                             "each": count(b, 1, "one near each corner")}}}},
        made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("R06")
def _r06(b: NumberedBrief) -> Draft:
    return draft("pipe flange", [
        item("disc", "cylinder", cite(b, "disc"), diameter=mm(b, 80, "80 mm across"), length=mm(b, 10, "10 mm thick"),
             axis=choose("z", assumed("a flange lies flat"))),
        item("bore", "hole", cite(b, "bore"), on=on("disc", "+end"), diameter=mm(b, 30, "30 mm bore"),
             depth=through(b, "through the centre"), place={"x": at(b, "the centre"), "y": at(b, "the centre")}),
        item("bolts", "hole", cite(b, "bolt holes"), on=on("disc", "+end"), diameter=mm(b, 8, "8 mm"),
             depth=through(b, "all the way through the disc"), count=count(b, 4, "Four"),
             place={"x": middle("the bolt circle is on the flange's centre"),
                    "y": middle("the bolt circle is on the flange's centre"),
                    "pattern": {"circle": {"count": count(b, 4, "Four"), "diameter": mm(b, 60, "60 mm bolt circle"),
                                           "start": assumed("where the first bolt is round the circle doesn't matter",
                                                            0, "deg")}}}),
    ], material=made_of(b, "steel"), silent=[no_load(b)])  # fmt: skip


@drafts("R07")
def _r07(b: NumberedBrief) -> Draft:
    return draft("pulley hub", [
        item("flange", "cylinder", cite(b, "flange disc"), diameter=mm(b, 50, "50 mm across"),
             length=mm(b, 6, "6 mm thick"), axis=choose("z", assumed("the flange lies flat"))),
        item("hub", "boss", cite(b, "round hub"), on=on("flange", "+end"), diameter=mm(b, 25, "25 mm across"),
             height=mm(b, 15, "15 mm tall"), place={"x": at(b, "centred"), "y": at(b, "centred")}),
        item("bore", "hole", cite(b, "bore"), on=on("hub", "+end"), diameter=mm(b, 10, "10 mm bore"),
             depth=through(b, "runs through both the flange and the hub"),
             place={"concentric": {"item": "hub", "from": said(b, "the hub")}}),
        item("holes", "hole", cite(b, "holes"), on=on("flange", "+end"), diameter=mm(b, 5, "5 mm"),
             depth=through(b, "through the flange only"), count=count(b, 3, "Three"),
             place={"x": middle("the circle is on the flange's centre"), "y": middle("the circle is on the flange's centre"),
                    "pattern": {"circle": {"count": count(b, 3, "Three"), "diameter": mm(b, 38, "38 mm circle"),
                                           "start": assumed("where the first hole is round the circle doesn't matter",
                                                            0, "deg")}}}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("R08")
def _r08(b: NumberedBrief) -> Draft:
    return draft("open-top box", [
        item("box", "block", cite(b, "open-top box"), length=mm(b, 60, "60 mm long"), width=mm(b, 40, "40 mm wide"),
             height=mm(b, 30, "30 mm tall")),
        item("hollow", "shell", cite(b, "walls"), of="box", thickness=mm(b, 2, "2 mm walls"),
             floor=mm(b, 2, "2 mm thick floor"), open={"faces": ["+z"], "from": said(b, "The top is completely open")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("R09")
def _r09(b: NumberedBrief) -> Draft:
    def holes(
        id_: str, host: str, face: str, nth: int, depth: str, along: dict[str, Any]
    ) -> dict[str, Any]:
        return item(id_, "hole", cite(b, "holes", nth), on=on(host, face), diameter=mm(b, 5, "5 mm holes", nth),
                    depth=through(b, depth), count=count(b, 2, "Two", nth),
                    place={"y": middle("the pair is centred across the width"), **along,
                           "pattern": {"row": {"axis": choose("y", said(b, "across its width", nth)),
                                               "pitch": mm(b, 20, "20 mm apart", nth),
                                               "count": count(b, 2, "Two", nth)}}})  # fmt: skip

    return draft("L-bracket", [
        item("base", "block", cite(b, "base leg"), length=mm(b, 50, "50 mm long"), width=mm(b, 40, "40 mm wide"),
             height=mm(b, 5, "5 mm thick")),
        item("upright", "block", cite(b, "upright leg"), on=on("base", "+z"), length=mm(b, 5, "5 mm thick"),
             width=mm(b, 40, "40 mm wide"),
             height=formula(35, "40 mm - 5 mm", cite(b, "40 mm tall") + cite(b, "5 mm thick")),
             place={"x": {"side": "+x", "distance": assumed("it stands on the back end, flush with it", 0),
                          "to": "edge"},
                    "y": middle("it spans the base's width")}),
        holes("base_holes", "base", "+z", 1, "pass through the base",
              {"x": {"side": "-x", "distance": mm(b, 25, "centred 25 mm from the front end"), "to": "centre"}}),
        holes("upright_holes", "upright", "-x", 2, "pass through the upright",
              {"z": {"side": "-z", "to": "centre",
                     "distance": formula(20, "25 mm - 5 mm",
                                         cite(b, "centred 25 mm above the bottom") + cite(b, "5 mm thick"))}}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


def _cantilever(
    b: NumberedBrief, name: str, bar: dict[str, Any], hole: str, apart: str
) -> Draft:
    """A bar fixed by two bolt holes near one end, a load on its free end (R10, L01 to L03): its shape, and its load case left to stage 6."""
    return draft(name, [
        item("bar", "block", cite(b, "bar") if "bar" in b.text else cite(b, "arm"), **bar),
        item("bolts", "hole", cite(b, "bolt holes"), on=on("bar", "+z"), diameter=mm(b, *_mm_of(hole)),
             depth=through(b, "bolt holes"), count=count(b, 2, "two"),
             place={"x": {"side": "-x", "to": "centre",
                          "distance": assumed("near that end: the first half the bar's width in",
                                              bar["width"]["value"] / 2)},
                    "y": middle("on the bar's centre line"),
                    "pattern": {"row": {"axis": choose("x", assumed("one behind the other along the bar: side by "
                                                                    "side, they'd leave no wall at its edges")),
                                        "pitch": mm(b, *_mm_of(apart)), "count": count(b, 2, "two")}}}),
    ], material=made_of(b, _material(b)),
       not_modelled=[left_out(b, "fixed at one end", "where it is held: the load case's, checked from stage 6"),
                     left_out(b, _sentence_with(b, "load of") if "load of" in b.text else _sentence_with(b, "N load"),
                              "a load case: checked from stage 6"),
                     left_out(b, _sentence_with(b, "safety factor"), "a strength requirement: checked from stage 6")])  # fmt: skip


def _mm_of(phrase: str) -> tuple[float, str]:
    """A size phrase's own number, and the phrase ("5 mm" -> 5, "5 mm")."""
    return float(phrase.split()[0]), phrase


def _material(b: NumberedBrief) -> str:
    for name in ("6061-T6 aluminium", "PLA", "aluminium"):
        if name in b.text:
            return name
    raise AssertionError("no material named")


def _sentence_with(b: NumberedBrief, phrase: str) -> str:
    """The text of the sentence ``phrase`` is in, without its full stop."""
    sentence = b.sentences[b.word(cite(b, phrase.split()[0])[0]).sentence]
    first, last = b.words[sentence.words[0]], b.words[sentence.words[-1]]
    return b.text[first.start : last.end]


@drafts("R10")
def _r10(b: NumberedBrief) -> Draft:
    return _cantilever(b, "cantilever bracket",
                       {"length": mm(b, 60, "60 mm long"), "width": mm(b, 20, "20 mm wide"),
                        "height": mm(b, 6, "6 mm thick")}, "5 mm", "15 mm apart")  # fmt: skip


def _spacer(b: NumberedBrief, base: dict[str, Any], post: dict[str, Any], fillet: float, bore: float,
            holes: tuple[float, float], limit: str) -> Draft:  # fmt: skip
    """A printed spacer block: a plate, a post in its middle with a fillet at its root, a hole down it, two mounting holes (R01, R11)."""
    hole, apart = holes
    return draft("spacer block", [
        item("base", "block", cite(b, "base"), **base),
        item("post", "boss", cite(b, "post"), on=on("base", "+z"),
             place={"x": at(b, "in the middle of it"), "y": at(b, "in the middle of it")}, **post),
        item("root", "fillet", cite(b, "fillet"), radius=mm(b, fillet, f"{fillet:g} mm fillet"),
             edges={"of": "post", "which": "joint", "where_meets": "base",
                    "words": cite(b, "where the post meets the plate")}),
        item("bore", "hole", cite(b, f"{bore:g} mm hole"), on=on("post", "+end"), diameter=mm(b, bore, f"{bore:g} mm"),
             depth=through(b, "all the way through the post and the plate"),
             place={"concentric": {"item": "post", "from": said(b, "through the post")}}),
        item("mounting", "hole", cite(b, "mounting holes"), on=on("base", "+z"),
             diameter=mm(b, hole, f"{hole:g} mm"), depth=through(b, "all the way through the plate"),
             count=count(b, 2, "Two"),
             place={"x": middle("the pair is centred on the plate"), "y": middle("on the plate's centre line"),
                    "pattern": {"row": {"axis": choose("x", assumed("along the plate")),
                                        "pitch": mm(b, apart, f"{apart:g} mm apart"), "count": count(b, 2, "Two")}}}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "3D-printed", "how it is made"),
                     left_out(b, limit, "a mass limit: checked from stage 6")],
       silent=[no_load(b)])  # fmt: skip


@drafts("R11")
def _r11(b: NumberedBrief) -> Draft:
    return _spacer(b, {"length": mm(b, 30, "30 mm square"), "width": mm(b, 30, "30 mm square"),
                       "height": mm(b, 4, "4 mm thick")},
                   {"diameter": mm(b, 12, "12 mm diameter"), "height": mm(b, 10, "10 mm tall")}, 2, 5, (3, 20),
                   "It must weigh no more than 8 g")  # fmt: skip


@drafts("R12")
def _r12(b: NumberedBrief) -> Draft:
    return draft("shaft collar", [
        item("collar", "tube", cite(b, "shaft collar"), outer_diameter=mm(b, 25, "25 mm"),
             inner_diameter=mm(b, 12, "12 mm bore"), length=mm(b, 15, "15 mm long"),
             axis=choose("z", assumed("a collar is drawn standing up"))),
        item("set_screws", "hole", cite(b, "set screw holes"), on=on("collar", "side"), diameter=mm(b, 4, "4 mm"),
             depth=through(b, "through the wall from the outside into the bore"), count=count(b, 2, "Two"),
             place={"z": at(b, "halfway along the length"),
                    "angle": assumed("which way round the first screw faces doesn't matter", 0, "deg"),
                    "pattern": {"arc": {"count": count(b, 2, "both"), "step": mm(b, 90, "90 degrees", unit="deg")}}}),
    ], material=made_of(b, "machined aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("R13")
def _r13(b: NumberedBrief) -> Draft:
    return draft("motor mount plate", [
        item("plate", "block", cite(b, "base plate"), length=mm(b, 60, "60 mm long"), width=mm(b, 40, "40 mm wide"),
             height=mm(b, 6, "6 mm thick")),
        item("boss", "boss", cite(b, "cylindrical boss"), on=on("plate", "+z"), diameter=mm(b, 18, "18 mm in diameter"),
             height=mm(b, 25, "25 mm tall"),
             place={"x": at(b, "in the middle of the plate"), "y": at(b, "in the middle of the plate")}),
        item("root", "fillet", cite(b, "fillet"), radius=mm(b, 2, "2 mm fillet"),
             edges={"of": "boss", "which": "joint", "where_meets": "plate",
                    "words": cite(b, "where the boss meets the plate")}),
        item("bore", "hole", cite(b, "shaft bore"), on=on("boss", "+end"), diameter=mm(b, 8, "8 mm"),
             depth=through(b, "all the way through the boss and the plate"),
             place={"concentric": {"item": "boss", "from": said(b, "on the boss axis")}}),
        item("mounting", "hole", cite(b, "mounting holes"), on=on("plate", "+z"), diameter=mm(b, 4.5, "4.5 mm"),
             depth=through(b, "all the way through the plate"), count=count(b, 4, "Four"),
             place={"x": at(b, "centred on the plate"), "y": at(b, "centred on the plate"),
                    "pattern": {"rectangle": {"x": mm(b, 44, "44 mm"), "y": mm(b, 24, "24 mm")}}}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "3D-printed", "how it is made"),
                     left_out(b, "The finished part must stand no taller than 32 mm and weigh no more than 30 g",
                              "a height and a mass limit: checked from stage 6")],
       silent=[no_load(b)])  # fmt: skip


@drafts("R14")
def _r14(b: NumberedBrief) -> Draft:
    return draft("standoff", [
        item("base", "block", cite(b, "base plate"), length=mm(b, 50, "50 mm square"),
             width=mm(b, 50, "50 mm square"), height=mm(b, 5, "5 mm thick")),
        item("standoff", "boss", cite(b, "cylindrical standoff"), on=on("base", "+z"),
             diameter=mm(b, 25, "25 mm across"), height=mm(b, 30, "30 mm tall"),
             place={"x": middle("a standoff sits in the middle of its base"),
                    "y": middle("a standoff sits in the middle of its base")}),
        item("hole", "hole", cite(b, "8 mm hole"), on=on("standoff", "+end"), diameter=mm(b, 8, "8 mm"),
             depth={"through": True, "from": assumed("a standoff's hole runs right through")},
             place={"concentric": {"item": "standoff", "from": said(b, "down the middle of the standoff")}}),
    ], material=made_of(b, "6061-T6 aluminium"))  # fmt: skip


# ----------------------------------------------------------------------
# P: single shapes
# ----------------------------------------------------------------------
@drafts("P01")
def _p01(b: NumberedBrief) -> Draft:
    side = mm(b, 30, "30 mm cube")
    return draft("cube", [item("cube", "block", cite(b, "cube"), length=side, width=side, height=side)],
                 material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P02")
def _p02(b: NumberedBrief) -> Draft:
    return draft("block", [item("block", "block", cite(b, "block"), length=mm(b, 80, "80 mm long"),
                                width=mm(b, 40, "40 mm wide"), height=mm(b, 25, "25 mm tall"))],
                 material=made_of(b, "steel"), silent=[no_load(b)])  # fmt: skip


def _rod(b: NumberedBrief, name: str, words: str, diameter: str, length: str, material: str,
         axis: dict[str, Any] | None = None) -> Draft:  # fmt: skip
    """A plain round rod or disc (P03, P05, P12, P14, V07, V08)."""
    return draft(name, [item(name.replace(" ", "_"), "cylinder", cite(b, words), diameter=mm(b, *_mm_of(diameter)),
                             length=mm(b, *_mm_of(length)),
                             axis=axis or choose("z", assumed("it is drawn standing up; which way doesn't matter")))],
                 material=made_of(b, material), silent=[no_load(b)] if "load case" in b.text else [])  # fmt: skip


@drafts("P03")
def _p03(b: NumberedBrief) -> Draft:
    return _rod(b, "rod", "rod", "12 mm in diameter", "100 mm long", "aluminium")


@drafts("P04")
def _p04(b: NumberedBrief) -> Draft:
    return draft("sphere", [item("sphere", "sphere", cite(b, "sphere"), diameter=mm(b, 40, "40 mm in diameter"),
                                 portion=choose("whole", said(b, "sphere")))],
                 material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P05")
def _p05(b: NumberedBrief) -> Draft:
    return _rod(b, "disc", "disc", "50 mm across", "3 mm thick", "stainless steel",
                choose("z", assumed("a disc lies flat")))  # fmt: skip


@drafts("P06")
def _p06(b: NumberedBrief) -> Draft:
    r, h = 10.0, 8.660254
    corners = [(r / 2, h), (-r / 2, h), (-r, 0.0), (-r / 2, -h), (r / 2, -h), (r, 0.0)]
    return draft("hexagonal prism", [
        item("prism", "extrusion", cite(b, "hexagonal prism"), length=mm(b, 30, "30 mm tall"),
             axis=choose("z", said(b, "tall")),
             profile={"start": [r, 0.0], "segments": [{"line_to": [x, y]} for x, y in corners],
                      "from": {"words": span(b, "hexagonal prism, 20 mm across the corners")}}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P07")
def _p07(b: NumberedBrief) -> Draft:
    return draft("dome", [item("dome", "sphere", cite(b, "dome"), diameter=mm(b, 50, "50 mm sphere"),
                               portion=choose("upper_half", said(b, "exactly half of a")))],
                 material=made_of(b, "PLA"),
                 not_modelled=[left_out(b, "sitting flat side down", "how it sits: a dome is drawn flat side down")],
                 silent=[no_load(b)])  # fmt: skip


@drafts("P08")
def _p08(b: NumberedBrief) -> Draft:
    return draft("tube", [
        item("tube", "cylinder", cite(b, "tube"), diameter=mm(b, 30, "30 mm outside diameter"),
             length=mm(b, 80, "80 mm long"), axis=choose("z", assumed("a tube is drawn standing up"))),
        item("hollow", "shell", cite(b, "inside diameter"), of="tube",
             thickness=formula(3, "(30 mm - 24 mm) / 2", cite(b, "30 mm outside diameter") +
                               cite(b, "24 mm inside diameter")),
             open={"faces": ["+end", "-end"], "from": said(b, "open at both ends")}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("P09")
def _p09(b: NumberedBrief) -> Draft:
    return draft("tag", [
        item("tag", "block", cite(b, "tag"), length=mm(b, 50, "50 mm"), width=mm(b, 30, "30 mm"),
             height=mm(b, 3, "3 mm thick")),
        item("corners", "fillet", cite(b, "rounded corners"), radius=mm(b, 5, "5 mm rounded corners"),
             edges={"of": "tag", "which": "vertical", "words": cite(b, "corners")}),
        item("hole", "hole", cite(b, "4 mm hole"), on=on("tag", "+z"), diameter=mm(b, 4, "4 mm"),
             depth={"through": True, "from": assumed("a tag's hole goes through it")},
             place={"x": {"side": "-x", "distance": mm(b, 6, "centred 6 mm"), "to": "centre"},
                    "y": middle("on the tag's centre line")}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "3D-printed", "how it is made"),
                     left_out(b, "one short end", "which short end: either; the spec measures from the -x end")],
       silent=[no_load(b)])  # fmt: skip


@drafts("P10")
def _p10(b: NumberedBrief) -> Draft:
    return draft("obround plate", [
        item("plate", "block", cite(b, "obround plate"), length=mm(b, 60, "60 mm long overall"),
             width=mm(b, 20, "20 mm wide"), height=mm(b, 4, "4 mm thick")),
        item("ends", "fillet", cite(b, "fully rounded ends"),
             radius=formula(10, "20 mm / 2", cite(b, "20 mm wide with fully rounded ends")),
             edges={"of": "plate", "which": "vertical", "words": cite(b, "rounded ends")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P11")
def _p11(b: NumberedBrief) -> Draft:
    ring = [
        {"arc_to": [16.0, 4.0], "centre": [20.0, 4.0]},
        {"arc_to": [24.0, 4.0], "centre": [20.0, 4.0]},
    ]
    return draft("ring", [
        item("ring", "revolution", cite(b, "ring shaped like a doughnut"),
             axis=choose("z", assumed("a ring lies flat")),
             profile={"start": [24.0, 4.0], "segments": ring,
                      "from": said(b, "an 8 mm round section bent into a full ring 40 mm across at the centre line")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P12")
def _p12(b: NumberedBrief) -> Draft:
    return _rod(b, "roller", "roller", "30 mm in diameter", "50 mm long", "PLA",
                choose("x", said(b, "its axis along X")))  # fmt: skip


@drafts("P13")
def _p13(b: NumberedBrief) -> Draft:
    return draft("shim", [item("shim", "block", cite(b, "shim"), length=mm(b, 40, "40 mm square"),
                               width=mm(b, 40, "40 mm square"), height=mm(b, 1, "1 mm thick"))],
                 material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("P14")
def _p14(b: NumberedBrief) -> Draft:
    return _rod(b, "pin", "pin", "3 mm in diameter", "60 mm long", "steel")


# ----------------------------------------------------------------------
# H: holes of every kind
# ----------------------------------------------------------------------
def _plate(
    b: NumberedBrief, id_: str, words: str, length: str, width: str, height: str
) -> dict[str, Any]:
    return item(id_, "block", cite(b, words), length=mm(b, *_mm_of(length)), width=mm(b, *_mm_of(width)),
                height=mm(b, *_mm_of(height)))  # fmt: skip


def _row(
    b: NumberedBrief, n: int, said_n: str, pitch: str, axis: dict[str, Any]
) -> dict[str, Any]:
    return {
        "row": {
            "axis": axis,
            "pitch": mm(b, *_mm_of(pitch)),
            "count": count(b, n, said_n),
        }
    }


GOES_THROUGH = {
    "through": True,
    "from": assumed("a hole in a plate goes through it unless the brief says how deep"),
}


@drafts("H01")
def _h01(b: NumberedBrief) -> Draft:
    return draft("strip", [
        _plate(b, "strip", "strip", "120 mm long", "25 mm wide", "5 mm thick"),
        item("holes", "hole", cite(b, "holes"), on=on("strip", "+z"), diameter=mm(b, 6, "6 mm"), depth=GOES_THROUGH,
             count=count(b, 5, "five"),
             place={"x": at(b, "the row centred on the strip"), "y": at(b, "along its centre line"),
                    "pattern": _row(b, 5, "five", "20 mm apart", choose("x", said(b, "in a row along its centre line")))}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("H02")
def _h02(b: NumberedBrief) -> Draft:
    return draft("perforated plate", [
        _plate(b, "plate", "perforated plate", "60 mm square", "60 mm square", "3 mm thick"),
        item("holes", "hole", cite(b, "holes"), on=on("plate", "+z"), diameter=mm(b, 6, "6 mm"),
             depth={"through": True, "from": said(b, "perforated")},
             place={"x": at(b, "centred on the plate"), "y": at(b, "centred on the plate"),
                    "pattern": {"grid": {"count_x": count(b, 3, "3", 2), "count_y": count(b, 3, "3", 3),
                                         "pitch_x": mm(b, 18, "18 mm centres"),
                                         "pitch_y": mm(b, 18, "18 mm centres")}}}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("H03")
def _h03(b: NumberedBrief) -> Draft:
    return draft("counterbored plate", [
        _plate(b, "plate", "plate", "60 mm long", "40 mm wide", "10 mm thick"),
        item("holes", "hole", cite(b, "counterbored holes"), on=on("plate", "+z"), diameter=mm(b, 5.5, "5.5 mm"),
             depth=through(b, "through hole"), count=count(b, 2, "two"),
             counterbore={"diameter": mm(b, 10, "10 mm counterbore"), "depth": mm(b, 5, "5 mm deep")},
             place={"x": middle("the pair is centred along the plate"), "y": middle("on the plate's centre line"),
                    "pattern": _row(b, 2, "two", "40 mm apart", choose("x", said(b, "along the length")))}),
    ], material=made_of(b, "steel"),
       not_modelled=[left_out(b, "for M5 screws", "what the holes are for: the brief gives their sizes")],
       silent=[no_load(b)])  # fmt: skip


@drafts("H04")
def _h04(b: NumberedBrief) -> Draft:
    return draft("countersunk plate", [
        _plate(b, "plate", "plate", "50 mm long", "30 mm wide", "6 mm thick"),
        item("holes", "hole", cite(b, "countersunk holes"), on=on("plate", "+z"), diameter=mm(b, 4.5, "4.5 mm"),
             depth=GOES_THROUGH, count=count(b, 2, "two"),
             countersink={"diameter": mm(b, 9, "9 mm across"), "angle": mm(b, 90, "90 degrees", unit="deg")},
             place={"x": middle("the pair is centred along the plate"), "y": middle("on the plate's centre line"),
                    "pattern": _row(b, 2, "two", "30 mm apart", choose("x", said(b, "along its length")))}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("H05")
def _h05(b: NumberedBrief) -> Draft:
    side = mm(b, 40, "40 mm")
    return draft("cube with a blind hole", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        item("hole", "hole", cite(b, "10 mm hole") + span(b, "The hole does not go all the way through"),
             on=on("cube", "+z"), diameter=mm(b, 10, "10 mm"), depth=mm(b, 25, "25 mm deep"),
             place={"x": at(b, "the middle of its top face"), "y": at(b, "the middle of its top face")}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


@drafts("H06")
def _h06(b: NumberedBrief) -> Draft:
    return draft("block with a hole along it", [
        _plate(b, "block", "block", "50 mm long", "30 mm wide", "30 mm tall"),
        item("hole", "hole", cite(b, "8 mm hole"), on=on("block", "+x"), diameter=mm(b, 8, "8 mm"),
             depth=through(b, "straight through it along its length"),
             place={"y": at(b, "through the middle"), "z": at(b, "through the middle")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("H07")
def _h07(b: NumberedBrief) -> Draft:
    side = mm(b, 30, "30 mm")
    centre = at(b, "through its centre")

    def hole(id_: str, face: str, axes: str) -> dict[str, Any]:
        return item(id_, "hole", cite(b, "holes"), on=on("cube", face), diameter=mm(b, 10, "10 mm"),
                    depth=through(b, "passing through its centre"), count=count(b, 1, "one"),
                    place=dict.fromkeys(axes, centre))  # fmt: skip

    return draft("cube with crossing holes", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        hole("hole_z", "+z", "xy"), hole("hole_x", "+x", "yz"), hole("hole_y", "+y", "xz"),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "three", "how many holes in all: one item each, one along each axis")],
       silent=[no_load(b)])  # fmt: skip


@drafts("H08")
def _h08(b: NumberedBrief) -> Draft:
    side = mm(b, 20, "20 mm")
    return draft("cube with a tapped hole", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        item("hole", "hole", cite(b, "threaded hole"), on=on("cube", "+z"),
             diameter={"value": 5.0, "unit": "mm", "from": {"table": "tapped:M6", "words": cite(b, "M6")}},
             depth=through(b, "straight through its centre top to bottom"),
             place={"x": at(b, "its centre"), "y": at(b, "its centre")}),
    ], material=made_of(b, "steel"),
       not_modelled=[left_out(b, "threaded", "an inside thread isn't modelled: the hole is made at its tap drill's size")],
       silent=[no_load(b)])  # fmt: skip


@drafts("H09")
def _h09(b: NumberedBrief) -> Draft:
    return draft("plate with holes of two sizes", [
        _plate(b, "plate", "plate", "80 mm", "40 mm", "4 mm thick"),
        item("centre_hole", "hole", cite(b, "12 mm hole"), on=on("plate", "+z"), diameter=mm(b, 12, "12 mm"),
             depth=GOES_THROUGH, place={"x": at(b, "in its centre"), "y": at(b, "in its centre")}),
        item("holes", "hole", cite(b, "4 mm holes"), on=on("plate", "+z"), diameter=mm(b, 4, "4 mm holes"),
             depth=GOES_THROUGH, count=count(b, 2, "two"),
             place={"x": middle("the pair is centred along the plate"), "y": middle("on the plate's centre line"),
                    "pattern": _row(b, 2, "two", "60 mm apart", choose("x", said(b, "along its length")))}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("H10")
def _h10(b: NumberedBrief) -> Draft:
    return draft("disc with a hole circle", [
        item("disc", "cylinder", cite(b, "disc"), diameter=mm(b, 70, "70 mm across"), length=mm(b, 6, "6 mm thick"),
             axis=choose("z", assumed("a disc lies flat"))),
        item("holes", "hole", cite(b, "holes"), on=on("disc", "+end"), diameter=mm(b, 5, "5 mm"), depth=GOES_THROUGH,
             count=count(b, 6, "six"),
             place={"x": middle("the circle is on the disc's centre"), "y": middle("the circle is on the disc's centre"),
                    "pattern": {"circle": {"count": count(b, 6, "six"), "diameter": mm(b, 50, "50 mm circle"),
                                           "start": assumed("where the first hole is round the circle doesn't matter",
                                                            0, "deg")}}}),
    ], material=made_of(b, "aluminium"), silent=[no_load(b)])  # fmt: skip


# ----------------------------------------------------------------------
# C: combinations
# ----------------------------------------------------------------------
@drafts("C01")
def _c01(b: NumberedBrief) -> Draft:
    return draft("stand", [
        _plate(b, "base", "base plate", "60 mm long", "40 mm wide", "6 mm thick"),
        item("post", "boss", cite(b, "round post"), on=on("base", "+z"), diameter=mm(b, 20, "20 mm across"),
             height=mm(b, 30, "30 mm tall"), place={"x": at(b, "centred"), "y": at(b, "centred")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


def _full(b: NumberedBrief, value: float, phrase: str, full: str) -> dict[str, Any]:
    """A length as long as another's, the brief says: the other's number, cited with the words that say so."""
    return {
        "value": value,
        "unit": "mm",
        "from": {"words": cite(b, phrase) + cite(b, full)},
    }


@drafts("C02")
def _c02(b: NumberedBrief) -> Draft:
    return draft("T-bar", [
        _plate(b, "bar", "flat bar", "80 mm long", "20 mm wide", "5 mm thick"),
        item("rib", "rib", cite(b, "rib"), on=on("bar", "+z"), length=_full(b, 80, "80 mm long", "for its full length"),
             thickness=mm(b, 5, "5 mm thick rib"), height=mm(b, 30, "30 mm tall"),
             along=choose("x", said(b, "standing along the middle of it")),
             place={"x": at(b, "for its full length"), "y": at(b, "the middle of it")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C03")
def _c03(b: NumberedBrief) -> Draft:
    return draft("U-channel", [
        item("base", "block", cite(b, "base"), length=mm(b, 100, "100 mm long"), width=mm(b, 40, "40 mm wide"),
             height=mm(b, 4, "4 mm thick")),
        item("walls", "rib", cite(b, "side walls"), on=on("base", "+z"),
             length=_full(b, 100, "100 mm long", "long edges of the base"),
             thickness=mm(b, 4, "4 mm thick", 2),
             height=formula(26, "30 mm - 4 mm", cite(b, "30 mm tall overall") + cite(b, "4 mm thick")),
             along=choose("x", said(b, "stand along")), count=count(b, 2, "two"),
             place={"x": at(b, "long edges of the base"), "pattern": {"ends": {"axis": choose("y", said(b, "both long edges")),
                                         "inset": formula(2, "4 mm / 2", cite(b, "4 mm thick", 2))}}}),
    ], material=made_of(b, "steel"),
       not_modelled=[left_out(b, "lies flat", "how it lies: the base is drawn flat, the walls standing up")],
       silent=[no_load(b)])  # fmt: skip


@drafts("C04")
def _c04(b: NumberedBrief) -> Draft:
    return draft("stepped shaft", [
        item("large", "cylinder", cite(b, "section"), diameter=mm(b, 20, "20 mm in diameter"),
             length=mm(b, 30, "30 mm long"), axis=choose("z", assumed("a shaft is drawn standing up"))),
        item("small", "cylinder", cite(b, "section", 2), on=on("large", "+end"),
             diameter=mm(b, 12, "12 mm in diameter"), length=mm(b, 40, "40 mm long"),
             place={"concentric": {"item": "large", "from": said(b, "on one axis")}}),
    ], material=made_of(b, "aluminium"),
       not_modelled=[left_out(b, "one", "how many axes: the two sections share one, the second on the first's end")],
       silent=[no_load(b)])  # fmt: skip


@drafts("C05")
def _c05(b: NumberedBrief) -> Draft:
    return draft("pin with a ball", [
        item("rod", "cylinder", cite(b, "rod"), diameter=mm(b, 6, "6 mm rod"), length=mm(b, 50, "50 mm long"),
             axis=choose("z", said(b, "standing upright"))),
        item("ball", "sphere", cite(b, "ball"), on=on("rod", "+end"), diameter=mm(b, 12, "12 mm ball"),
             portion=choose("whole", said(b, "ball")),
             place={"x": at(b, "centred on its top end"), "y": at(b, "centred on its top end")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C08")
def _c08(b: NumberedBrief) -> Draft:
    side = mm(b, 40, "40 mm on the outside")
    return draft("sealed hollow cube", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        item("hollow", "shell", cite(b, "sealed hollow"), of="cube", thickness=mm(b, 2, "2 mm walls on every side"),
             open={"faces": [], "from": said(b, "completely closed")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C09")
def _c09(b: NumberedBrief) -> Draft:
    return draft("cup", [
        item("cup", "cylinder", cite(b, "cup"), diameter=mm(b, 60, "60 mm outside diameter"),
             length=mm(b, 80, "80 mm tall"), axis=choose("z", said(b, "tall"))),
        item("hollow", "shell", cite(b, "walls"), of="cup", thickness=mm(b, 2, "2 mm walls"),
             floor=mm(b, 3, "3 mm floor"), open={"faces": ["+end"], "from": said(b, "open at the top")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C10")
def _c10(b: NumberedBrief) -> Draft:
    return draft("tray with a divider", [
        _plate(b, "tray", "tray", "100 mm long", "60 mm wide", "25 mm tall"),
        item("hollow", "shell", cite(b, "walls"), of="tray", thickness=mm(b, 2, "2 mm walls"),
             floor=mm(b, 2, "2 mm floor"), open={"faces": ["+z"], "from": said(b, "open at the top")}),
        item("divider", "rib", cite(b, "divider wall"), on=on("tray", "inner -z"),
             length=formula(56, "60 mm - 2 * 2 mm", cite(b, "60 mm wide") + cite(b, "2 mm walls")),
             thickness=mm(b, 2, "2 mm thick divider"),
             height=formula(23, "25 mm - 2 mm", cite(b, "25 mm tall") + cite(b, "2 mm floor")),
             along=choose("y", said(b, "across the middle")), count=count(b, 1, "one"),
             place={"x": at(b, "across the middle"), "y": middle("it spans the tray from wall to wall")}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "splitting it into two equal compartments",
                              "what the divider makes: two compartments, across the middle")],
       silent=[no_load(b)])  # fmt: skip


@drafts("C11")
def _c11(b: NumberedBrief) -> Draft:
    return draft("plate with two posts", [
        _plate(b, "plate", "plate", "80 mm long", "30 mm wide", "5 mm thick"),
        item("posts", "boss", cite(b, "round posts"), on=on("plate", "+z"), diameter=mm(b, 10, "10 mm across"),
             height=mm(b, 20, "20 mm tall"), count=count(b, 2, "two"),
             place={"x": middle("the pair is centred along the plate"), "y": at(b, "centred across its width"),
                    "pattern": _row(b, 2, "two", "50 mm apart", choose("x", said(b, "along its length")))}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C12")
def _c12(b: NumberedBrief) -> Draft:
    return draft("disc with bumps", [
        item("disc", "cylinder", cite(b, "disc"), diameter=mm(b, 80, "80 mm across"), length=mm(b, 5, "5 mm thick"),
             axis=choose("z", assumed("a disc lies flat"))),
        item("bumps", "sphere", cite(b, "bumps"), on=on("disc", "+end"), diameter=mm(b, 8, "8 mm"),
             portion=choose("upper_half", said(b, "half-ball")),
             place={"x": middle("the circle is on the disc's centre"), "y": middle("the circle is on the disc's centre"),
                    "pattern": {"circle": {"count": count(b, 8, "eight"), "diameter": mm(b, 60, "60 mm circle"),
                                           "start": assumed("where the first bump is round the circle doesn't matter",
                                                            0, "deg")}}}),
    ], material=made_of(b, "aluminium"),
       not_modelled=[left_out(b, "equally spaced", "how they are spaced: a circle of copies is evenly spaced")],
       silent=[no_load(b)])  # fmt: skip


@drafts("C13")
def _c13(b: NumberedBrief) -> Draft:
    return draft("clevis", [
        _plate(b, "block", "block", "40 mm long", "20 mm wide", "10 mm thick"),
        item("ears", "post", cite(b, "ears"), on=on("block", "+z"), length=mm(b, 6, "6 mm thick"),
             width=mm(b, 20, "20 mm wide", 2), height=mm(b, 25, "25 mm tall"), count=count(b, 2, "two ears"),
             place={"y": middle("each ear spans the block's width"),
                    "pattern": {"ends": {"axis": choose("x", said(b, "rising from its two ends")),
                                         "inset": formula(3, "6 mm / 2", cite(b, "6 mm thick"))}}}),
        item("holes", "hole", cite(b, "8 mm hole"), on=on("ears", "+x"), diameter=mm(b, 8, "8 mm"),
             depth=through(b, "straight through it"),
             place={"z": {"side": "+z", "distance": mm(b, 8, "centred 8 mm below its top"), "to": "centre"},
                    "y": middle("across the ear's width, in its middle")}),
    ], material=made_of(b, "steel"),
       silent=[no_load(b)])  # fmt: skip


@drafts("C14")
def _c14(b: NumberedBrief) -> Draft:
    side = mm(b, 30, "30 mm cube")
    return draft("ornament", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        item("ball", "sphere", cite(b, "ball"), on=on("cube", "+z"), diameter=mm(b, 20, "20 mm ball"),
             portion=choose("whole", said(b, "ball")),
             place={"x": at(b, "the middle of its top face"), "y": at(b, "the middle of its top face")}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "half sunk into", "how deep it sits: a whole ball standing on a face is centred "
                                                   "on it, half in"),
                     left_out(b, "so half the ball sticks up", "the same: half of it stands out of the face")],
       silent=[no_load(b)])  # fmt: skip


@drafts("C15")
def _c15(b: NumberedBrief) -> Draft:
    ball = {"diameter": mm(b, 16, "16 mm ball"), "portion": choose("whole", said(b, "ball")),
            "place": {"y": at(b, "centred on each end of it"), "z": at(b, "centred on each end of it")}}  # fmt: skip
    return draft("dumbbell", [
        item("bar", "block", cite(b, "bar"), length=mm(b, 50, "50 mm long"), width=mm(b, 10, "10 mm square"),
             height=mm(b, 10, "10 mm square")),
        item("ball_plus", "sphere", cite(b, "ball"), on=on("bar", "+x"), **ball),
        item("ball_minus", "sphere", cite(b, "ball"), on=on("bar", "-x"), **ball),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("C16")
def _c16(b: NumberedBrief) -> Draft:
    return draft("mounting bracket", [
        item("plate", "block", cite(b, "plate"), length=mm(b, 60, "60 mm"), width=mm(b, 40, "40 mm"),
             height=mm(b, 8, "8 mm thick")),
        item("boss", "boss", cite(b, "boss"), on=on("plate", "+z"), diameter=mm(b, 20, "20 mm diameter"),
             height=mm(b, 15, "15 mm tall"),
             place={"x": at(b, "rises from the middle"), "y": at(b, "rises from the middle")}),
        item("root", "fillet", cite(b, "fillet"), radius=mm(b, 3, "3 mm fillet"),
             edges={"of": "boss", "which": "joint", "where_meets": "plate", "words": cite(b, "at its root")}),
        item("bore", "hole", cite(b, "bore"), on=on("boss", "+end"), diameter=mm(b, 10, "10 mm bore"),
             depth=through(b, "runs through the boss and the plate"),
             place={"concentric": {"item": "boss", "from": said(b, "through the boss")}}),
        item("bolts", "hole", cite(b, "bolt holes"), on=on("plate", "+z"), diameter=mm(b, 6, "6 mm bolt holes"),
             depth=through(b, "pass through the plate"), count=count(b, 4, "Four"),
             place={"x": middle("the rectangle is centred on the plate"),
                    "y": middle("the rectangle is centred on the plate"),
                    "pattern": {"rectangle": {"x": mm(b, 44, "44 mm"), "y": mm(b, 24, "24 mm")}}}),
    ], material=made_of(b, "machined aluminium"), silent=[no_load(b)])  # fmt: skip


UNDRAFTED["C06"] = (
    "six rods round a pole, 60 degrees apart: Forge stands items round a rod's side a quarter "
    "turn apart only, for now (the spec checks say UNABLE)"
)
UNDRAFTED["C07"] = ("three rods crossing through one another's middles: every body after the first stands on an "
                    "earlier one's face, so none can pass through another")  # fmt: skip


# ----------------------------------------------------------------------
# A: abstract shapes
# ----------------------------------------------------------------------
UNDRAFTED["A01"] = (
    "a cube and a ball, only what they share: no kind keeps what two bodies share"
)
UNDRAFTED["A02"] = (
    "a ball cut out of a cube: no kind cuts a ball's shape (a pocket is flat-bottomed)"
)
UNDRAFTED["A03"] = ("balls fused in a row: every body after the first stands on an earlier one's flat face, and "
                    "a ball has none")  # fmt: skip
UNDRAFTED["A04"] = (
    "a bar turned 45 degrees: a body runs along a frame axis or out of a face, never at an angle"
)


@drafts("A05")
def _a05(b: NumberedBrief) -> Draft:
    return draft("hollow ball", [
        item("ball", "sphere", cite(b, "ball"), diameter=mm(b, 40, "40 mm across"),
             portion=choose("whole", said(b, "ball"))),
        item("hollow", "shell", cite(b, "sealed hollow"), of="ball", thickness=mm(b, 3, "3 mm wall"),
             open={"faces": [], "from": said(b, "sealed")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


UNDRAFTED["A06"] = (
    "a hole drilled into a ball: Forge cuts into flat faces and round sides, not a ball's surface"
)


@drafts("A07")
def _a07(b: NumberedBrief) -> Draft:
    thick = mm(b, 10, "each 10 mm thick")
    centred = {"concentric": {"item": "bottom", "from": said(b, "centred")}}
    return draft("tower of discs", [
        item("bottom", "cylinder", cite(b, "bottom one"), diameter=mm(b, 40, "40 mm across"), length=thick,
             axis=choose("z", said(b, "stacked on top of each other"))),
        item("middle", "cylinder", cite(b, "middle one"), on=on("bottom", "+end"), diameter=mm(b, 30, "30 mm across"),
             length=thick, place=centred),
        item("top", "cylinder", cite(b, "top one"), on=on("middle", "+end"), diameter=mm(b, 20, "20 mm across"),
             length=thick, place=centred),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "three", "how many discs in all: one item each"),
                     *({"words": cite(b, "one", k), "reason": "'the bottom one': a disc it names, not a count"}
                       for k in (1, 2, 3))],
       silent=[no_load(b)])  # fmt: skip


@drafts("A08")
def _a08(b: NumberedBrief) -> Draft:
    half = {"length": mm(b, 10, "10 mm wide"), "width": mm(b, 5, "5 mm thick"),
            "height": formula(20, "(50 mm - 10 mm) / 2", cite(b, "50 mm long") + cite(b, "10 mm wide")),
            "place": {"x": at(b, "crossing at their middles"),
                      "z": middle("the bars are one flat plate, 5 mm thick")}}  # fmt: skip
    return draft("plus sign", [
        item("bar", "block", cite(b, "bars"), length=mm(b, 50, "50 mm long"), width=mm(b, 10, "10 mm wide"),
             height=mm(b, 5, "5 mm thick")),
        item("half_plus", "post", cite(b, "at right angles"), on=on("bar", "+y"), **half),
        item("half_minus", "post", cite(b, "at right angles"), on=on("bar", "-y"), **half),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "two", "how many bars: the first is one block, the second its two halves "
                                       "standing on the first's sides")],
       silent=[no_load(b)])  # fmt: skip


# ----------------------------------------------------------------------
# V: one plate, asked many ways
# ----------------------------------------------------------------------
def _four_holes(b: NumberedBrief, plate: dict[str, Any], diameter: dict[str, Any], depth: dict[str, Any],
                x: dict[str, Any], y: dict[str, Any], material: dict[str, Any] | None, *,
                holes: str = "holes", count_: dict[str, Any] | None = None, centred: dict[str, Any] | None = None,
                each: dict[str, Any] | None = None, **rest: Any) -> Draft:  # fmt: skip
    """The suite's plate with four holes on a rectangle (V01 to V05, V11)."""
    where = centred or middle("the rectangle is centred on the plate")
    rectangle: dict[str, Any] = {"x": x, "y": y, **({"each": each} if each else {})}
    hole = {"words": cite(b, holes), "diameter": diameter, "depth": depth,
            **({"count": count_} if count_ else {}),
            "place": {"x": where, "y": where, "pattern": {"rectangle": rectangle}}}  # fmt: skip
    return _plate_of_four(b, "mounting plate", plate, hole, material, **rest)


THROUGH_A_PLATE = {
    "through": True,
    "from": assumed("holes in a mounting plate go through it"),
}


@drafts("V01")
def _v01(b: NumberedBrief) -> Draft:
    size = "70x50x4mm"
    return _four_holes(b, {"words": cite(b, "plate"), "length": mm(b, 70, size), "width": mm(b, 50, size),
                           "height": mm(b, 4, size)},
                       mm(b, 4, "4mm holes"), THROUGH_A_PLATE, mm(b, 56, "56x36mm"), mm(b, 36, "56x36mm"),
                       made_of(b, "aluminium"), count_=count(b, 4, "4x"))  # fmt: skip


def _unit_after(
    b: NumberedBrief, value: float, number: str, unit: str = "mm"
) -> dict[str, Any]:
    """A size whose unit the brief gives once, after its numbers ("70 by 50 and 4 thick (mm)")."""
    return {
        "value": value,
        "unit": unit,
        "from": {"words": cite(b, number) + cite(b, unit)},
    }


@drafts("V02")
def _v02(b: NumberedBrief) -> Draft:
    return _four_holes(b, {"words": cite(b, "plate"), "length": _unit_after(b, 70, "70"),
                           "width": _unit_after(b, 50, "50"), "height": _unit_after(b, 4, "4 thick")},
                       mm(b, 4, "4mm hole"), THROUGH_A_PLATE, mm(b, 56, "56 apart"), mm(b, 36, "36 the other"),
                       made_of(b, "aluminum"), holes="hole",
                       not_modelled=[left_out(b, "one way", "which way is which: the 56 mm along the plate's length, "
                                                            "the 36 mm across, as its sides are")],
                       silent=[quiet(b, "nothing heavy", "it says nothing heavy goes on it: no load")])  # fmt: skip


@drafts("V03")
def _v03(b: NumberedBrief) -> Draft:
    return _four_holes(b, {"words": cite(b, "mounting plate"), "length": mm(b, 70, "L 70 mm"),
                           "width": mm(b, 50, "W 50 mm"), "height": mm(b, 4, "T 4 mm")},
                       mm(b, 4, "diameter 4 mm"), through(b, "through holes"), mm(b, 56, "56"),
                       mm(b, 36, "36 mm"), made_of(b, "aluminium 6061-T6"), count_=count(b, 4, "4x"),
                       centred=at(b, "centred"),
                       silent=[quiet(b, "Load", "it says there is no load")])  # fmt: skip


@drafts("V04")
def _v04(b: NumberedBrief) -> Draft:
    return _four_holes(b, {"words": cite(b, "plate"), "length": mm(b, 7, "7 cm long", unit="cm"),
                           "width": mm(b, 5, "5 cm wide", unit="cm"),
                           "height": mm(b, 0.4, "0.4 cm thick", unit="cm")},
                       mm(b, 4, "4 mm holes"), THROUGH_A_PLATE, mm(b, 5.6, "5.6 cm", unit="cm"),
                       mm(b, 3.6, "3.6 cm", unit="cm"), made_of(b, "aluminium"), count_=count(b, 4, "four"),
                       centred=at(b, "centred on the plate"), silent=[no_load(b)])  # fmt: skip


@drafts("V05")
def _v05(b: NumberedBrief) -> Draft:
    return _four_holes(b, {"words": cite(b, "plate"), "length": mm(b, 70, "70 mm long"),
                           "width": mm(b, 50, "50 mm wide"), "height": mm(b, 4, "4 mm thick")},
                       mm(b, 4, "4 mm holes"), through(b, "go through"), mm(b, 56, "56 mm"), mm(b, 36, "36 mm"),
                       made_of(b, "aluminium"), count_=count(b, 4, "Four"),
                       each=count(b, 1, "one near each corner"), silent=[no_load(b)])  # fmt: skip


@drafts("V06")
def _v06(b: NumberedBrief) -> Draft:
    return draft("plate with a hole", [
        item("plate", "block", cite(b, "plate"), length=mm(b, 3, "3 inches long", unit="in"),
             width=mm(b, 2, "2 inches wide", unit="in"), height=mm(b, 0.25, "0.25 inches thick", unit="in")),
        item("hole", "hole", cite(b, "hole"), on=on("plate", "+z"), diameter=mm(b, 0.5, "0.5 inch hole", unit="in"),
             depth=through(b, "through the middle"),
             place={"x": at(b, "the middle"), "y": at(b, "the middle")}),
    ], material=made_of(b, "steel"), silent=[no_load(b)])  # fmt: skip


@drafts("V07")
def _v07(b: NumberedBrief) -> Draft:
    return _rod(
        b,
        "disc",
        "disc",
        "76 mm across",
        "25 mm thick",
        "PLA",
        choose("z", assumed("a disc lies flat")),
    )


@drafts("V08")
def _v08(b: NumberedBrief) -> Draft:
    return draft("cylinder", [
        item("cylinder", "cylinder", cite(b, "cylinder"), diameter=mm(b, 30, "diameter should be 30 millimetres"),
             length=mm(b, 45, "height should be 45 millimetres"), axis=choose("z", said(b, "height"))),
    ], material=made_of(b, "stainless steel"),
       silent=[quiet(b, "Nothing", "it says nothing pushes on it: no load")])  # fmt: skip


@drafts("V09")
def _v09(b: NumberedBrief) -> Draft:
    return draft("washer", [
        item("washer", "tube", cite(b, "washer"), outer_diameter=mm(b, 30, "30mm od"),
             inner_diameter=mm(b, 12, "12mm id"), length=mm(b, 3, "3mm thick"),
             axis=choose("z", assumed("a washer lies flat"))),
    ], material=made_of(b, "pla"))  # fmt: skip


UNDRAFTED["V10"] = "Romanian: Forge reads English briefs only"


@drafts("V11")
def _v11(b: NumberedBrief) -> Draft:
    return _four_holes(b, {"words": cite(b, "plate"), "length": mm(b, 70, "70 mm long"),
                           "width": mm(b, 50, "50 mm wide"), "height": mm(b, 4, "4 mm thick")},
                       mm(b, 4, "4 mm holes"), THROUGH_A_PLATE, mm(b, 56, "56 mm"), mm(b, 36, "36 mm"), None,
                       count_=count(b, 4, "four"), silent=[no_load(b)])  # fmt: skip


# ----------------------------------------------------------------------
# L: loads and limits (checked from stage 6; their shapes are drafted)
# ----------------------------------------------------------------------
@drafts("L01")
def _l01(b: NumberedBrief) -> Draft:
    return _cantilever(b, "cantilever bracket",
                       {"length": mm(b, 60, "60 mm long"), "width": mm(b, 20, "20 mm wide"),
                        "height": mm(b, 6, "6 mm thick")}, "5 mm", "15 mm apart")  # fmt: skip


@drafts("L02")
def _l02(b: NumberedBrief) -> Draft:
    return _l01(b)


@drafts("L03")
def _l03(b: NumberedBrief) -> Draft:
    return _cantilever(b, "cantilever arm",
                       {"length": mm(b, 100, "100 mm long"), "width": mm(b, 25, "25 mm wide"),
                        "height": mm(b, 8, "8 mm thick")}, "6 mm", "20 mm apart")  # fmt: skip


@drafts("L04")
def _l04(b: NumberedBrief) -> Draft:
    return draft("bearing block", [
        _plate(b, "block", "bearing block", "40 mm long", "30 mm wide", "20 mm tall"),
        item("pin_hole", "hole", cite(b, "10 mm hole"), on=on("block", "+y"), diameter=mm(b, 10, "10 mm hole"),
             depth=through(b, "straight through it"),
             place={"x": at(b, "through the middle"), "z": at(b, "through the middle")}),
    ], material=made_of(b, "6061-T6 aluminium"),
       not_modelled=[left_out(b, "across its 30 mm width", "which way it goes: across the width, the 30 mm the "
                                                           "block's width already is"),
                     left_out(b, "for a pin", "what the hole is for"),
                     left_out(b, "The pin carries 2000 N", "a load case: checked from stage 6"),
                     left_out(b, "The bearing stress must keep a safety factor of at least 3",
                              "a strength requirement: checked from stage 6")])  # fmt: skip


def _cube(b: NumberedBrief, side: str, material: str, limit: str) -> Draft:
    size = mm(b, *_mm_of(side))
    return draft("cube", [item("cube", "block", cite(b, "cube"), length=size, width=size, height=size)],
                 material=made_of(b, material),
                 not_modelled=[left_out(b, limit, "a mass limit: checked from stage 6")], silent=[no_load(b)])  # fmt: skip


@drafts("L05")
def _l05(b: NumberedBrief) -> Draft:
    return _cube(b, "20 mm cube", "1018 steel", "It must weigh no more than 50 g")


@drafts("L06")
def _l06(b: NumberedBrief) -> Draft:
    return _cube(b, "20 mm on each side", "PLA", "It must weigh no more than 15 g")


@drafts("L07")
def _l07(b: NumberedBrief) -> Draft:
    return draft("post on a base", [
        item("base", "block", cite(b, "base"), length=mm(b, 40, "40 mm square"), width=mm(b, 40, "40 mm square"),
             height=mm(b, 5, "5 mm thick")),
        item("post", "boss", cite(b, "post"), on=on("base", "+z"), diameter=mm(b, 15, "15 mm across"),
             height=mm(b, 40, "40 mm tall"), place={"x": at(b, "centred"), "y": at(b, "centred")}),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "The whole part must be no taller than 50 mm", "a height limit: checked from stage 6")],
       silent=[no_load(b)])  # fmt: skip


# ----------------------------------------------------------------------
# X: what V1 had to turn back
# ----------------------------------------------------------------------
UNDRAFTED["X01"] = ("nothing sized: every value of a washer would be assumed, and the honest answer is a question "
                    "(the spec writer's; test_v2_false_passes, case 22)")  # fmt: skip
UNDRAFTED["X02"] = ("gear teeth: no kind cuts a tooth, and a disc with the teeth listed as not modelled is no gear: "
                    "the person decides whether to have it")  # fmt: skip


@drafts("X03")
def _x03(b: NumberedBrief) -> Draft:
    r, h = 6.5 / math.cos(math.pi / 6), 6.5
    corners = [(r / 2, h), (-r / 2, h), (-r, 0.0), (-r / 2, -h), (r / 2, -h), (r, 0.0)]
    return draft("hex bolt", [
        item("head", "extrusion", cite(b, "standard hex head"),
             length=assumed("an M8 hex head is 5.3 mm high (ISO 4017)", 5.3),
             axis=choose("z", assumed("a bolt is drawn standing on its head")),
             profile={"start": [r, 0.0], "segments": [{"line_to": [x, y]} for x, y in corners],
                      "from": {"assumed": "an M8 hex head is 13 mm across its flats (ISO 4017)"}}),
        item("shank", "boss", cite(b, "bolt"), on=on("head", "+end"),
             diameter=assumed("an M8 bolt's shank is 8 mm across, its thread's major diameter", 8),
             height=mm(b, 40, "40 mm long"),
             place={"x": middle("a bolt's shank is on its head's axis"), "y": middle("a bolt's shank is on its head's axis")}),
        item("thread", "thread", cite(b, "M8"), of="shank",
             designation={"text": "M8", "from": {"words": cite(b, "M8")}},
             hand=choose("right", assumed("a standard thread is right-handed"))),
    ], material=made_of(b, "steel"), silent=[no_load(b)])  # fmt: skip


@drafts("X04")
def _x04(b: NumberedBrief) -> Draft:
    return draft("cone", [
        item("cone", "cone", cite(b, "cone"), base_diameter=mm(b, 40, "40 mm across the base"),
             top_diameter=assumed("coming to a point: nothing across at its top", 0),
             length=mm(b, 60, "60 mm tall"), axis=choose("z", said(b, "tall"))),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


UNDRAFTED["X05"] = "a coil spring: no kind sweeps a wire along a helix"


@drafts("X06")
def _x06(b: NumberedBrief) -> Draft:
    side = mm(b, 20, "20 mm")
    return draft("cube with a hole", [
        item("cube", "block", cite(b, "cube"), length=side, width=side, height=side),
        item("hole", "hole", cite(b, "30 mm hole"), on=on("cube", "+z"), diameter=mm(b, 30, "30 mm hole"),
             depth=through(b, "straight through it"),
             place={"x": middle("the brief doesn't say where: the middle"),
                    "y": middle("the brief doesn't say where: the middle")}),
    ], material=made_of(b, "PLA"), silent=[no_load(b)])  # fmt: skip


@drafts("X07")
def _x07(b: NumberedBrief) -> Draft:
    return draft("sphere", [
        item("sphere", "sphere", cite(b, "sphere"), diameter=mm(b, 50, "50 mm in diameter"),
             portion=choose("whole", said(b, "sphere"))),
    ], material=made_of(b, "PLA"),
       not_modelled=[left_out(b, "The whole part must fit inside a 20 mm box", "a size limit: checked from stage 6")],
       silent=[no_load(b)])  # fmt: skip


UNDRAFTED["X08"] = "no part described: the honest answer is a question"
UNDRAFTED["X09"] = (
    "not a part: the spec writer turns it back (test_v2_false_passes, case 21)"
)
UNDRAFTED["X10"] = ("a heart's outline: the brief gives only its width, so its curves would be Forge's own, which a "
                    "person must see drawn first")  # fmt: skip
UNDRAFTED["X11"] = "no sizes and no load figure: the honest answer is a question"
UNDRAFTED["X12"] = ("two loose cubes: every body after the first stands on an earlier one's face, so a part is one "
                    "piece")  # fmt: skip
