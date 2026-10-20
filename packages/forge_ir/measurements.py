"""The measurement vocabulary: what a requirement can be checked against.

A requirement says what must be true. Something has to say *what to measure* to
find out, and the honest place for that is the document, declared by whoever
wrote the requirement.

The alternative -- inferring the measurement from the requirement's wording, or
hard-coding a mapping from parameter names -- was tried first and is a trap. It
works beautifully on the example it was written against and silently checks the
wrong thing, or nothing at all, on the next design. A pipeline that looks for a
parameter called ``pivot_diameter`` verifies exactly one part in the world.

So requirements carry a ``measurement`` binding drawn from the closed vocabulary
below. A requirement with a threshold and no binding is reported ``NOT_TESTED``
-- visibly unchecked, rather than quietly assumed satisfied.

Vocabulary
----------

===================================  =======================================
``mass``                             component mass, needs a material
``volume``                           enclosed volume
``surface_area``                     boundary area
``bounding_box_x`` ``_y`` ``_z``     overall extent along each axis
``centre_of_mass_x`` ``_y`` ``_z``   centroid coordinate
``minimum_wall_thickness``           thinnest through-section found
``wall_thickness``                   a container's side walls, at half its
                                     height through the middle of its
                                     footprint, thinnest to thickest
``floor_thickness``                  a container's floor, at the middle of
                                     its footprint
``opening_depth``                    how far down from the top the middle of
                                     the part is open; 0 when it is closed
``roundness_about_z``                1 when every width across the XY plane
                                     is the same, as on a cylinder
``roundness``                        the same, about the part's roundest axis
``roundness_every_way``              1 when the part is the same width in
                                     every direction in space, as a ball is
``sealed_voids``                     how many pockets of air the part closes
                                     in on every side, with no way out: 0
                                     for a solid part, 1 for a sealed
                                     hollow box
``parameter:<id>``                   a resolved design parameter
``interface_size:<id>``              nominal size of a declared interface
``entity:<name>:<key>``              a published entity's own dimension,
                                     e.g. ``entity:shaft.bore:diameter``
``safety_factor:bearing``            bearing margin at a bore interface
``safety_factor:pin_shear``          double-shear margin of the pin
``safety_factor:bending``            root bending margin of a straight bar
                                     bolted at one end, loaded at the other
``footprint_side:<mm>``              the part's X or Y extent, whichever
                                     is nearer that figure: "40 mm wide"
                                     said of the whole part, whichever way
                                     it is turned on the plate
``extent_side:<mm>``                 the same over X, Y and Z
``bend_angle``                       how far a bent or curved part turns,
                                     in deg, read on its finished surface;
                                     0 for a flat part
``bend_count``                       how many separate bends it has
``bend_centre``                      the middle of its (first) bend, in mm
                                     along the part from its nearer end
``bend_off_centre``                  how far that is from the part's middle
``bend_spread``                      how much of its length the bend takes
``bent_along``                       its flat size in the way it bends along
``bend_convex``                      1 when the face that was up when flat
                                     is on the outside of its bend, -1 inside
``flat_extent_side:<mm>``            the part's size laid flat, every bend
                                     undone, along the axis nearest the
                                     figure: "70 mm long" said of a curved
                                     plate
``ends_round:<mm>``                  how far, in mm, the part's two ends
                                     along its longer side are from
                                     semicircles of that radius, seen from
                                     above: "both ends fully rounded"
``flat_face:<side>``                 the area of the part lying flat in the
                                     plane of its outermost face on that
                                     side: a dome flat side down has its
                                     whole disc there, and touches its top
                                     plane at a point
``opening_at:<size>:<where>``        how far, in mm, the nearest opening
                                     right through the part of that size
                                     (``8.2`` round, ``28x5`` a slot) is
                                     from where it should be, read on the
                                     part laid flat. ``<where>`` is
                                     ``<along>,<across>``: ``along`` the flat
                                     part's longer side, ``across`` its
                                     shorter; each is ``lo<mm>``,
                                     ``hi<mm>`` (in from that end),
                                     ``end<mm>`` (in from either end),
                                     ``side<mm>`` (the same, across),
                                     ``mid`` or ``mid+<mm>``/``mid-<mm>``
``openings_on_circle:<d>:<D>``       how many openings of diameter d right
                                     through the part have their centres on
                                     the D mm circle about its middle, read
                                     laid flat: a bolt circle
``windows_of_size:<L>x<W>``          how many openings of that length and
                                     width go through a wall of the part --
                                     a window in one wall of a hollow shell
                                     as much as a slot through a plate --
                                     read on rays along each axis
``walls_crossed:<d>``                the most separate walls any open hole
                                     of diameter d cuts: 1 through a plate
                                     or one wall of a shell, 2 when it runs
                                     on through the facing wall
``hole_at:<d>:<x>,<y>,<z>``          how many open holes of diameter d have
                                     their axis through that point, to
                                     0.5 mm, in the part's own coordinates;
                                     `*` for a coordinate the brief leaves
                                     free -- "at X/Z positions (-36, 50)"
                                     is `hole_at:4.5:-36,*,50`
``openings_apart:<d>:<s>``           how many pairs of openings of diameter
                                     d right through the part have their
                                     centres s mm apart, read laid flat:
                                     "two 8.2 mm holes spaced 60 mm apart"
``counterbores:<d>:<D>x<h>,<side>``   how many d mm holes right through the
                                     part are counterbored D across and h
                                     deep from its top or bottom face, read
                                     on the part laid flat
``standing_at:<D>x<h>:<where>``      how far, in mm, the round solid D
                                     across standing h proud of the part's
                                     top is from where it should be, laid
                                     flat: a boss "in the centre"
``feature_count:<kind>``             how many features of a kind exist
``angle_between:<kind>:<tag>``       the angle between the axes of the two
                                     features of that kind carrying that tag
===================================  =======================================

``entity:<name>:diameter`` is accepted as sugar for twice the radius, because
engineers specify bores by diameter and the geometry stores a radius, and making
the author do that arithmetic invites the one error the units layer exists to
prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Literal, Mapping

#: Bindings that take no argument.
SIMPLE_MEASUREMENTS: tuple[str, ...] = (
    "mass",
    "volume",
    "surface_area",
    "bounding_box_x",
    "bounding_box_y",
    "bounding_box_z",
    "centre_of_mass_x",
    "centre_of_mass_y",
    "centre_of_mass_z",
    "minimum_wall_thickness",
    "wall_thickness",
    "floor_thickness",
    "opening_depth",
    "roundness_about_z",
    "roundness",
    "roundness_every_way",
    "sealed_voids",
    "bend_angle",
    "bend_count",
    "bend_centre",
    "bend_off_centre",
    "bend_spread",
    "bent_along",
    "bend_convex",
)

#: The measurements of a container, which take the side it is open on:
#: `opening_depth` is open from the top, `opening_depth:left` from the left.
CONTAINER_MEASUREMENTS: tuple[str, ...] = (
    "wall_thickness", "floor_thickness", "opening_depth")
#: Each side by the axis it faces along and which way: +1 the high end.
CONTAINER_SIDES: Mapping[str, tuple[int, int]] = {
    "top": (2, 1), "bottom": (2, -1), "right": (0, 1), "left": (0, -1),
    "back": (1, 1), "front": (1, -1),
}

#: Bindings of the form ``prefix:argument``.
PARAMETERISED_MEASUREMENTS: tuple[str, ...] = (
    "parameter",
    "interface_size",
    "entity",
    "safety_factor",
    "feature_count",
    "angle_between",
    "holes_of_diameter",
    "openings_of_size",
    "opening_at",
    "openings_on_circle",
    "openings_apart",
    "hole_at",
    "walls_crossed",
    "windows_of_size",
    "counterbores",
    "standing_at",
    "footprint_side",
    "extent_side",
    "flat_face",
    "flat_extent_side",
    "ends_round",
)

#: Valid arguments for ``safety_factor:``.
SAFETY_FACTOR_KINDS: tuple[str, ...] = ("bearing", "pin_shear", "bending")

#: What each binding measures, as a unit its threshold must be convertible
#: to -- "" for a pure number. The ONE place this is written down.
#:
#: It used to be written in two others as well, by hand, and they drifted. The
#: requirements role kept its own tuple of which bindings are dimensionless:
#: `("safety_factor", "feature_count")`. When `roundness_about_z` joined the
#: vocabulary, that tuple did not, and the very first requirement Forge
#: carried with it -- `roundness_about_z at_least 0.95`, unit "" -- was
#: rejected by Forge's own validator for having an empty unit, and sent back
#: to the model to fix. The model had never written it. It returned the same
#: answer twice and the run died in under five minutes.
#:
#: Every binding in the vocabulary must appear here; a test asserts it, so the
#: next addition fails loudly at test time instead of silently at run time.
#: Parameterised bindings whose dimension depends on the argument -- a
#: `parameter:` is whatever the parameter is, an `entity:` whatever its key
#: measures -- are listed as None: any real unit is accepted.
MEASURED_IN: Mapping[str, str | None] = {
    "mass": "kg",
    "volume": "mm^3",
    "surface_area": "mm^2",
    "bounding_box_x": "mm",
    "bounding_box_y": "mm",
    "bounding_box_z": "mm",
    "centre_of_mass_x": "mm",
    "centre_of_mass_y": "mm",
    "centre_of_mass_z": "mm",
    "minimum_wall_thickness": "mm",
    "wall_thickness": "mm",
    "floor_thickness": "mm",
    "opening_depth": "mm",
    "roundness_about_z": "",
    "roundness": "",
    "roundness_every_way": "",
    "sealed_voids": "",
    "parameter": None,
    "interface_size": "mm",
    "entity": None,
    "safety_factor": "",
    "feature_count": "",
    "angle_between": "deg",
    "holes_of_diameter": "",
    "openings_of_size": "",
    "opening_at": "mm",
    "openings_on_circle": "",
    "openings_apart": "",
    "hole_at": "",
    "walls_crossed": "",
    "windows_of_size": "",
    "counterbores": "",
    "standing_at": "mm",
    "footprint_side": "mm",
    "extent_side": "mm",
    "flat_face": "mm^2",
    "bend_angle": "deg",
    "bend_count": "",
    "bend_centre": "mm",
    "bend_off_centre": "mm",
    "bend_spread": "mm",
    "bent_along": "mm",
    "bend_convex": "",
    "flat_extent_side": "mm",
    "ends_round": "mm",
}


def is_dimensionless(binding: str) -> bool:
    """Whether a binding's threshold is a pure number, read from `MEASURED_IN`."""
    head = binding.split(":", 1)[0].strip()
    return MEASURED_IN.get(head) == ""


def one_line_vocabulary() -> str:
    """Every binding in one line, generated from the vocabulary itself.

    The repair prompt used to carry a hand-written copy of this, and it never
    learned about `angle_between` or `roundness_about_z`: a model being told
    what it may write was shown a menu two entries out of date.
    """
    with_argument = {
        "parameter": "parameter:<parameter_id>",
        "interface_size": "interface_size:<interface_id>",
        "entity": "entity:<published_name>:<dimension>",
        "safety_factor": "safety_factor:" + "|".join(SAFETY_FACTOR_KINDS),
        "feature_count": "feature_count:<feature_kind>[:<tag>]",
        "angle_between": "angle_between:<feature_kind>:<tag>",
        "holes_of_diameter": "holes_of_diameter:<mm>[:on_axis]",
        "openings_of_size": "openings_of_size:<length>x<width>",
        "opening_at": "opening_at:<mm or LxW>:<along>,<across>",
        "openings_on_circle": "openings_on_circle:<hole mm>:<circle mm>",
        "openings_apart": "openings_apart:<hole mm>:<centres mm>",
        "hole_at": "hole_at:<hole mm>:<x>,<y>,<z>",
        "walls_crossed": "walls_crossed:<hole mm>",
        "windows_of_size": "windows_of_size:<length>x<width>[:-y]",
        "counterbores": "counterbores:<hole mm>:<diameter>x<depth>,top|bottom",
        "standing_at": "standing_at:<diameter>x<height>:<along>,<across>",
        "footprint_side": "footprint_side:<mm>",
        "extent_side": "extent_side:<mm>",
        "flat_face": "flat_face:" + "|".join(CONTAINER_SIDES),
        "flat_extent_side": "flat_extent_side:<mm>",
        "ends_round": "ends_round:<radius mm>",
    }
    return (
        "no-argument: " + ", ".join(SIMPLE_MEASUREMENTS) + ". With an "
        "argument: " + ", ".join(
            with_argument.get(head, f"{head}:<argument>")
            for head in PARAMETERISED_MEASUREMENTS
        ) + ". A container open on a side other than its top: "
        + ", ".join(f"{head}:<side>" for head in CONTAINER_MEASUREMENTS)
        + ", the side one of " + "|".join(CONTAINER_SIDES) + "."
    )


@dataclass(frozen=True, slots=True)
class MeasurementBinding:
    """A parsed ``measurement`` string."""

    kind: str
    argument: str = ""
    sub_argument: str = ""

    @property
    def is_simple(self) -> bool:
        return self.kind in SIMPLE_MEASUREMENTS

    def render(self) -> str:
        parts = [self.kind]
        if self.argument:
            parts.append(self.argument)
        if self.sub_argument:
            parts.append(self.sub_argument)
        return ":".join(parts)


class MeasurementError(ValueError):
    """A measurement binding is not in the vocabulary."""



#: Concepts that read like measurements and are not. Each is a real answer a
#: model gave, with what it should have written instead.
_NOT_MEASUREMENTS: dict[str, str] = {
    "load": "A load is not a property of the finished geometry -- nothing about "
    "the part reports the force applied to it. State the load as an assumption "
    "carrying a force value; what gets measured is the margin it produces, via "
    "`safety_factor:bearing`, `safety_factor:pin_shear` or "
    "`safety_factor:bending`.",
    "force": "See `load`: state it as an assumption, and measure the margin with "
    "`safety_factor:bearing`, `safety_factor:pin_shear` or "
    "`safety_factor:bending`.",
    "stress": "Stress is not measured directly. Use `safety_factor:bearing`, "
    "`safety_factor:pin_shear` or `safety_factor:bending`, which compare a "
    "computed stress against yield.",
    "material": "Material belongs in the component's `material` field, not in a "
    "requirement's threshold. A grade is not a number with a unit.",
    "material_grade": "Material belongs in the component's `material` field.",
    "cost": "Cost is not derivable from the geometry here.",
    "strength": "Use `safety_factor:bearing`, `safety_factor:pin_shear` or "
    "`safety_factor:bending`.",
    "deflection": "Deflection is not measured by this pipeline yet. Record the "
    "requirement without a `measurement` -- it will be reported NOT_TESTED, "
    "which is honest -- or drop it.",
    "temperature": "Temperature is not a property of the geometry.",
}


#: Words for things the feature vocabulary calls something else. A bolt hole is
#: a `hole`; asking for `feature_count:bolt` is the right idea in the wrong
#: dialect, and listing 22 kinds instead of answering wastes a repair round.
_KIND_SYNONYMS: dict[str, str] = {
    "bolt": "hole",
    "bolts": "hole",
    "screw": "hole",
    "fastener": "hole",
    "bolt_hole": "hole",
    "mounting_hole": "hole",
    "holes": "hole",
    "bore": "hole",
    "plate": "box",
    "block": "box",
    "boss": "cylinder",
    "shaft": "cylinder",
    "pin": "cylinder",
    "fillet": "union",
    "cut": "subtract",
    "pocket": "subtract",
}


def _nearest_kind(name: str, kinds: Any) -> str:
    lowered = name.strip().lower()
    if lowered in _KIND_SYNONYMS:
        return _KIND_SYNONYMS[lowered]
    for word, kind in _KIND_SYNONYMS.items():
        if word in lowered:
            return kind
    close = get_close_matches(lowered, list(kinds), n=1, cutoff=0.6)
    return close[0] if close else ""


def _all_bindings() -> str:
    """Every form, in one block. An error that lists half the vocabulary sends
    the reader back to pick another wrong answer from the same half."""
    return (
        "Bindings that take no argument: " + ", ".join(SIMPLE_MEASUREMENTS) + ".\n"
        "Bindings that take an argument: parameter:<parameter_id>, "
        "interface_size:<interface_id>, entity:<published_name>:<dimension>, "
        "safety_factor:bearing, safety_factor:pin_shear, safety_factor:bending, "
        "feature_count:<kind>, "
        "angle_between:<kind>:<tag>, holes_of_diameter:<mm>[:on_axis]."
    )


def _suggestion(name: str) -> str:
    """A pointed hint when the name is a known not-a-measurement, or close to
    something real."""
    lowered = name.strip().lower()
    for concept, advice in _NOT_MEASUREMENTS.items():
        if concept in lowered:
            return " " + advice
    close = get_close_matches(lowered, SIMPLE_MEASUREMENTS, n=1, cutoff=0.7)
    if close:
        return f" Did you mean `{close[0]}`?"
    for prefix in PARAMETERISED_MEASUREMENTS:
        if lowered.startswith(prefix):
            return (
                f" `{prefix}` takes an argument: write it as `{prefix}:<id>`."
            )
    return ""


#: An opening's size in an `opening_at`: a diameter, or a length by a width.
_OPENING_SIZE = re.compile(r"\d+(?:\.\d+)?(?:\s*[x*]\s*\d+(?:\.\d+)?)?")
#: Where along or across: in from an end or a side, or off the middle.
_A_PLACE = re.compile(r"(?:lo|hi|end|side)\d+(?:\.\d+)?|mid(?:[+-]\d+(?:\.\d+)?)?")


def parse_measurement(text: str) -> MeasurementBinding:
    """Parse a binding, refusing anything outside the vocabulary."""
    cleaned = text.strip()
    if not cleaned:
        raise MeasurementError("measurement binding is empty")

    head, _, tail = cleaned.partition(":")
    if tail and head in CONTAINER_MEASUREMENTS:
        # A container open on a side other than its top: `opening_depth:left`
        # measures from the left face in, `floor_thickness:left` the wall
        # opposite it, `wall_thickness:left` the four walls round the way in.
        if tail not in CONTAINER_SIDES:
            raise MeasurementError(
                f"`{head}:{tail}` names no side. The side a container is "
                "open on is one of " + ", ".join(CONTAINER_SIDES)
                + f"; `{head}` alone means the top.")
        return MeasurementBinding(head, tail)
    if not tail:
        if head not in SIMPLE_MEASUREMENTS:
            raise MeasurementError(
                f"unknown measurement '{head}'.{_suggestion(head)}"
            )
        return MeasurementBinding(head)

    if head not in PARAMETERISED_MEASUREMENTS:
        raise MeasurementError(
            f"unknown measurement '{head}'.{_suggestion(head)}"
        )

    if head == "entity":
        name, _, key = tail.partition(":")
        if not name or not key:
            # Almost always a `parameter:` binding wearing the wrong prefix.
            # `entity:` measures a published *face's* own size and only works
            # if some feature publishes that name -- a much stronger claim than
            # "the design declares this dimension", which is what the author
            # nearly always means.
            #
            # Observed live: four requirements in one set, every one of them
            # `entity:<something>` with no dimension key, every one of them
            # about a dimension the design was going to declare anyway.
            suggestion = name.replace(".", "_") if name else "the_dimension"
            raise MeasurementError(
                "an `entity` measurement needs both a published name and a "
                "dimension key, e.g. entity:shaft.bore:diameter. "
                f"If you mean a dimension the design declares, that is "
                f"`parameter:{suggestion}` -- the designer is then required to "
                "declare a parameter with that exact id. Use `entity:` only "
                "for the size of a face a feature publishes, such as a hole's "
                "bore."
            )
        return MeasurementBinding("entity", name, key)

    if head == "flat_face":
        # Which way a flat face is turned is a real side, unlike the axis in
        # a `bounding_box_*` equality: "flat side up" is about up.
        if tail not in CONTAINER_SIDES:
            raise MeasurementError(
                f"`flat_face:{tail}` names no side. The side is one of "
                + ", ".join(CONTAINER_SIDES) + ".")
        return MeasurementBinding("flat_face", tail)

    if head == "safety_factor" and tail not in SAFETY_FACTOR_KINDS:
        raise MeasurementError(
            f"unknown safety factor '{tail}'. Known: "
            f"{', '.join(SAFETY_FACTOR_KINDS)}"
        )

    if head == "feature_count":
        # A feature *kind*, not a feature id. The distinction is easy to miss --
        # `feature_count:mounting_holes` reads perfectly well and counts nothing,
        # because no feature has that kind. Caught here rather than silently
        # measuring zero.
        from .features import FEATURE_SPECS

        kind, _, tag = tail.partition(":")
        if kind not in FEATURE_SPECS:
            nearest = _nearest_kind(kind, FEATURE_SPECS)
            raise MeasurementError(
                f"`feature_count:{kind}` names no feature kind. It counts "
                "features of a kind, not features with an id or role."
                + (f" Did you mean `feature_count:{nearest}`?" if nearest else "")
            )
        if tail.count(":") > 1:
            raise MeasurementError(
                f"`feature_count:{tail}` has too many parts. The form is "
                "`feature_count:<kind>` or `feature_count:<kind>:<tag>`."
            )
        return MeasurementBinding("feature_count", kind, tag)

    if head == "angle_between":
        # The one binding that measures a RELATIONSHIP rather than a
        # quantity, and the gap it fills was open for a long time. "Two set
        # screws 90 degrees apart" was checkable only as `parameter:<id>`,
        # which reads back a number the design wrote about itself: a collar
        # whose two set screws were drilled parallel to the bore, 180 degrees
        # apart and opening into nothing, declared `angle = 90 deg` and every
        # geometric gate passed, because they were real holes that cut real
        # material. Nothing measured where they pointed.
        #
        # This does. It reads the axes off the built part, so it is true of
        # the object rather than of the paperwork, and it cannot be satisfied
        # by naming a parameter.
        from .features import FEATURE_SPECS

        kind, _, tag = tail.partition(":")
        if kind not in FEATURE_SPECS:
            nearest = _nearest_kind(kind, FEATURE_SPECS)
            raise MeasurementError(
                f"`angle_between:{kind}` names no feature kind."
                + (f" Did you mean `angle_between:{nearest}:<tag>`?"
                   if nearest else "")
            )
        if not tag:
            raise MeasurementError(
                f"`angle_between:{kind}` needs a tag saying WHICH two "
                f"features the angle is between: `angle_between:{kind}:<tag>`. "
                "A part usually has more features of a kind than the two the "
                "requirement is about -- a collar's bore is a `hole` just as "
                "its set screws are."
            )
        if tail.count(":") > 1:
            raise MeasurementError(
                f"`angle_between:{tail}` has too many parts. The form is "
                "`angle_between:<kind>:<tag>`."
            )
        return MeasurementBinding("angle_between", kind, tag)

    if head == "holes_of_diameter":
        # How many open holes of one size the finished part has. Counted off
        # the built geometry by diameter, so it needs no tag and no parameter
        # name to agree between two stages: "two 4 mm set screw holes" is
        # true of the object or it is not. A collar was released with both
        # set screws drawn at the bore's 12 mm and no bore at all, and every
        # claim passed, because every claim was about a name the design used.
        figure, _, where = tail.partition(":")
        try:
            size = float(figure)
        except ValueError:
            size = -1.0
        if size <= 0.0:
            raise MeasurementError(
                f"`holes_of_diameter:{figure}` needs a diameter in mm, e.g. "
                "`holes_of_diameter:4`."
            )
        if where not in ("", "on_axis"):
            raise MeasurementError(
                f"`holes_of_diameter:{tail}`: the only qualifier is "
                "`on_axis`, for holes running down the part's own axis."
            )
        return MeasurementBinding("holes_of_diameter", figure, where)

    if head == "openings_of_size":
        # How many openings right through the part, of one length and
        # width: "two 28 x 5 mm slots". Read off the built part, laid flat,
        # whatever drew them -- a slot profile, two holes and a box, a cut.
        sizes = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)\s*", tail)
        if not sizes or min(float(sizes.group(1)),
                            float(sizes.group(2))) <= 0.0:
            raise MeasurementError(
                f"`openings_of_size:{tail}` needs a length and a width in mm, "
                "e.g. `openings_of_size:28x5`.")
        return MeasurementBinding("openings_of_size", tail.strip())

    if head == "openings_on_circle":
        size, _, circle = tail.partition(":")
        try:
            figures = (float(size), float(circle))
        except ValueError:
            figures = (-1.0, -1.0)
        if min(figures) <= 0.0:
            raise MeasurementError(
                f"`openings_on_circle:{tail}` needs the hole's diameter and the "
                "circle's, in mm: `openings_on_circle:8:60`.")
        return MeasurementBinding("openings_on_circle", size.strip(),
                                  circle.strip())

    if head == "windows_of_size":
        # An optional third part: the wall it goes through, "-y" or "+x".
        tail, _, side = tail.partition(":")
        side = side.strip().lower()
        if side and not re.fullmatch(r"[+-][xyz]", side):
            raise MeasurementError(
                f"`windows_of_size:{tail}:{side}`: the wall is a sign and an "
                "axis, `-y` for the wall on the negative-Y side.")
        sizes = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)\s*", tail)
        if not sizes or min(float(sizes.group(1)),
                            float(sizes.group(2))) <= 0.0:
            raise MeasurementError(
                f"`windows_of_size:{tail}` needs a length and a width in mm, "
                "e.g. `windows_of_size:210x60`.")
        return MeasurementBinding("windows_of_size", f"{sizes.group(1)}x"
                                  f"{sizes.group(2)}", side)

    if head == "walls_crossed":
        try:
            figure = float(tail)
        except ValueError:
            figure = -1.0
        if figure <= 0.0:
            raise MeasurementError(
                f"`walls_crossed:{tail}` needs the hole's diameter in mm: "
                "`walls_crossed:4.5`.")
        return MeasurementBinding("walls_crossed", tail.strip())

    if head == "hole_at":
        size, _, where = tail.partition(":")
        places = [w.strip() for w in where.split(",")]
        try:
            hole = float(size)
            given = [float(w) for w in places if w != "*"]
        except ValueError:
            hole, given = -1.0, []
        if hole <= 0.0 or len(places) != 3 or len(given) < 2:
            raise MeasurementError(
                f"`hole_at:{tail}` needs the hole's diameter, then x,y,z in mm "
                "with `*` for at most one coordinate left free: "
                "`hole_at:8.5:0,0,-37.5`, `hole_at:4.5:-36,*,50`.")
        return MeasurementBinding("hole_at", size.strip(), ",".join(places))

    if head == "openings_apart":
        size, _, apart = tail.partition(":")
        try:
            figures = (float(size), float(apart))
        except ValueError:
            figures = (-1.0, -1.0)
        if min(figures) <= 0.0:
            raise MeasurementError(
                f"`openings_apart:{tail}` needs the hole's diameter and how far "
                "apart the centres are, in mm: `openings_apart:8.2:60`.")
        return MeasurementBinding("openings_apart", size.strip(),
                                  apart.strip())

    if head == "counterbores":
        size, _, rest = tail.partition(":")
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)\s*,"
                         r"\s*(top|bottom|any)\s*", rest)
        try:
            hole = float(size)
        except ValueError:
            hole = -1.0
        if hole <= 0.0 or not m or float(m.group(1)) <= hole or float(
                m.group(2)) <= 0.0:
            raise MeasurementError(
                f"`counterbores:{tail}` needs the hole's diameter, then the "
                "counterbore's diameter by its depth and the face it is cut "
                "from: `counterbores:5.5:10x4,top`.")
        return MeasurementBinding("counterbores", size.strip(),
                                  f"{m.group(1)}x{m.group(2)},{m.group(3)}")

    if head == "standing_at":
        size, _, where = tail.partition(":")
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)\s*",
                         size)
        places = [w.strip() for w in where.split(",")]
        if not m or min(float(m.group(1)), float(m.group(2))) <= 0.0 or len(
                places) != 2 or not all(_A_PLACE.fullmatch(w) for w in places):
            raise MeasurementError(
                f"`standing_at:{tail}` needs the round solid's diameter by how "
                "far it stands proud, then where it is along and across the "
                "part: `standing_at:36x6:mid,mid`.")
        return MeasurementBinding("standing_at",
                                  f"{m.group(1)}x{m.group(2)}", ",".join(places))

    if head == "opening_at":
        # Where an opening is: "two 8.2 mm holes on the centreline, the
        # first 18 mm from the end". Counting holes of 8.2 mm says nothing
        # about where they are; this reads it on the built part.
        size, _, where = tail.partition(":")
        if not _OPENING_SIZE.fullmatch(size.strip()):
            raise MeasurementError(
                f"`opening_at:{tail}`: the size is a diameter in mm (`8.2`) or "
                "a length and width (`28x5`).")
        places = [w.strip() for w in where.split(",")]
        if len(places) != 2 or not all(_A_PLACE.fullmatch(w) for w in places):
            raise MeasurementError(
                f"`opening_at:{tail}`: say where along the part and where "
                "across it, e.g. `opening_at:8.2:hi18,mid` -- each `lo<mm>`, "
                "`hi<mm>`, `end<mm>`, `side<mm>`, `mid`, `mid+<mm>` or "
                "`mid-<mm>`.")
        return MeasurementBinding("opening_at", size.strip(), ",".join(places))

    if head == "ends_round":
        # "Both ends fully rounded": each end of the part, along its longer
        # side, a semicircle of that radius seen from above.
        try:
            radius = float(tail)
        except ValueError:
            radius = -1.0
        if radius <= 0.0:
            raise MeasurementError(
                f"`ends_round:{tail}` needs the radius in mm, e.g. "
                "`ends_round:8` for a strip 16 mm wide.")
        return MeasurementBinding(head, tail)

    if head in ("footprint_side", "extent_side", "flat_extent_side"):
        try:
            size = float(tail)
        except ValueError:
            size = -1.0
        if size <= 0.0:
            raise MeasurementError(
                f"`{head}:{tail}` needs the figure in mm, e.g. `{head}:40`.")
        return MeasurementBinding(head, tail)

    return MeasurementBinding(head, tail)


#: What each whole-part binding actually measures.
#:
#: The list used to render bare -- `bounding_box_x` with no gloss beside it,
#: while `parameter:<id>` carried a description. Asked for a standoff on a
#: plate, the Requirements Engineer bound "the base plate shall be 5 mm thick"
#: to `bounding_box_z` and "the standoff shall be 25 mm across" to
#: `bounding_box_x`. Both measure the finished part's envelope, so both failed
#: against a design whose plate was exactly 5 mm and whose post was exactly 25.
#: Three false alarms on a correct part, which is the worst thing an evidence
#: system can produce.
_WHAT_IT_MEASURES: Mapping[str, str] = {
    "mass": "the whole part's mass",
    "volume": "the whole part's volume",
    "surface_area": "the whole part's surface area",
    "bounding_box_x": "the WHOLE part's overall extent in x",
    "bounding_box_y": "the WHOLE part's overall extent in y",
    "bounding_box_z": "the WHOLE part's overall extent in z",
    "centre_of_mass_x": "the whole part's centre of mass, x",
    "centre_of_mass_y": "the whole part's centre of mass, y",
    "centre_of_mass_z": "the whole part's centre of mass, z",
    "minimum_wall_thickness": "the thinnest wall anywhere in the part",
    "wall_thickness": "a container's side walls (a box, tray or cup), at "
                      "half its height",
    "floor_thickness": "a container's floor, under the middle of its space",
    "opening_depth": "how deep a container is open from its top; 0 if closed",
    "roundness_about_z": (
        "1 when the part is the same width across EVERY direction in the XY "
        "plane, as a cylinder is. A square block measures 0.707, a hexagon "
        "0.866. Bind a part the brief calls round -- a collar, a disc, a "
        "boss -- to this: two equal bounding boxes do NOT say a part is "
        "round, because a 25 mm square block has a 25 by 25 bounding box "
        "exactly as a 25 mm cylinder does"
    ),
    "roundness": (
        "the same as `roundness_about_z`, about whichever of X, Y or Z the "
        "part is roundest about -- for a round part whose brief does not say "
        "which way it lies, such as a pin or a shaft"
    ),
    "roundness_every_way": (
        "1 when the part is the same width in EVERY direction in space, as a "
        "ball is. A cylinder as tall as it is wide measures 0.707, a cube "
        "0.577. Bind a part the brief calls a sphere or a ball to this: a "
        "cylinder is round about its axis and has a ball's bounding box"
    ),
    "sealed_voids": (
        "how many pockets of air the part closes in on every side, with no "
        "way out: 0 for a solid part, 1 for a sealed hollow box. Read on the "
        "built part's surface, where a void is invisible from outside"
    ),
    "bend_angle": "how far a bent or curved part turns, in deg, read on its "
                  "finished surface -- every bend added up; 0 for a flat part",
    "bend_count": "how many separate bends or curves a part has",
    "bend_convex": "which way a bent part curves: 1 when the face that was "
                   "up when it was flat ends on the outside of the bend (an "
                   "arch, its curve's centre below), -1 on the inside (a "
                   "dish)",
    "bend_centre": "where the middle of its (first) bend is, in mm along the "
                   "part from its nearer end -- half its length for a bend in "
                   "the middle",
    "bend_off_centre": "how far the middle of its (first) bend is from the "
                       "middle of the part, in mm along it: 0 for a bend in "
                       "the middle",
    "bend_spread": "how much of the part's length, in mm along it, its "
                   "(first) bend is spread over: small for a fold, the whole "
                   "length for a curve end to end",
    "bent_along": "the part's size, laid flat, in the direction it bends "
                  "along: a 70 by 50 plate folded across its width bends "
                  "along its 70",
}


def vocabulary_help() -> str:
    """A compact description for the model-facing authoring guide."""
    simple = "\n".join(
        f"  - {name:22s} {_WHAT_IT_MEASURES.get(name, '')}"
        for name in SIMPLE_MEASUREMENTS
    )
    return (
        "Bind each numeric requirement to what measures it, with a "
        "`measurement` field. The threshold's unit must match what the binding "
        "measures: a length binding needs a length unit, and `safety_factor:` "
        "and `feature_count:` are dimensionless, so their unit is `\"\"`.\n\n"
        "**Choosing between them.** A claim about ONE NAMED DIMENSION -- a "
        "plate's thickness, a boss's diameter, a hole's size -- binds to "
        "`parameter:<id>`, naming the parameter you want the design to have. "
        "The designer is required to declare a parameter with that exact id, "
        "so the requirement checks the dimension itself. Only a claim about "
        "the finished part's overall envelope binds to `bounding_box_*`: on a "
        "post standing on a plate, `bounding_box_z` is the whole thing's "
        "height, not the plate's thickness and not the post's.\n\n"
        "**Counting a subset.** `feature_count:hole` counts EVERY hole in the "
        "part. A plate with a central bore and four bolt holes has five, so "
        "\"four mounting holes\" bound to `feature_count:hole` fails against a "
        "correct design. When the requirement is about some of them, name a "
        "tag: `feature_count:hole:mounting` counts only the holes the designer "
        "tagged `mounting`, and the designer is required to tag them.\n\n"
        "**An angle between two features.** \"Two set screws 90 degrees "
        "apart\" is not a dimension of anything and does not belong in "
        "`parameter:<id>`, which reads back a number the design writes about "
        "itself -- a collar declared `angle = 90 deg`, drilled both holes "
        "parallel to the bore, and the claim could not tell. Bind it to "
        "`angle_between:hole:set_screw`, which measures the angle between the "
        "two tagged holes on the finished part, in `deg`. Tag exactly two: "
        "the angle is between a pair, so three or one reports BLOCKED.\n\n"
        "Available bindings:\n"
        + simple + "\n"
        "  - parameter:<parameter_id>      the resolved value of a named design\n"
        "                                  parameter -- the usual choice for a\n"
        "                                  stated dimension, e.g.\n"
        "                                  parameter:plate_thickness\n"
        "  - interface_size:<interface_id> an interface's nominal size\n"
        "  - entity:<name>:<key>           a published entity's dimension,\n"
        "                                  e.g. entity:shaft.bore:diameter\n"
        "  - safety_factor:bearing | safety_factor:pin_shear |\n"
        "    safety_factor:bending       (a bar bolted at one end)\n"
        "  - feature_count:<kind>          counts features OF THAT KIND,\n"
        "                                  e.g. feature_count:hole -- not an id\n"
        "  - feature_count:<kind>:<tag>    counts only the ones carrying that\n"
        "                                  tag, e.g. feature_count:hole:mounting\n"
        "  - angle_between:<kind>:<tag>    the angle between the axes of the\n"
        "                                  TWO features carrying that tag, in\n"
        "                                  deg, measured on the built part,\n"
        "                                  e.g. angle_between:hole:set_screw\n"
        "  - holes_of_diameter:<mm>        how many open holes of that size the\n"
        "                                  built part has; add `:on_axis` for\n"
        "                                  holes down the part's own axis\n"
        "  - openings_of_size:<l>x<w>      how many openings right through the\n"
        "                                  part are that long and that wide --\n"
        "                                  slots, windows: openings_of_size:28x5\n"
        "  - opening_at:<size>:<along>,<across>  how far, in mm, the\n"
        "                                  nearest opening of that size (8.2 or\n"
        "                                  28x5) is from where the brief puts\n"
        "                                  it, on the part laid flat: along its\n"
        "                                  longer side and across it, each\n"
        "                                  lo<mm>/hi<mm>/end<mm>/side<mm> in from\n"
        "                                  an end or side, or mid / mid+<mm>.\n"
        "                                  Bind with `at_most` 0.5 mm\n"
        "  - openings_on_circle:<d>:<D>    how many d mm openings right through\n"
        "                                  the part are centred on the D mm\n"
        "                                  circle about its middle: a bolt circle\n"
        "  - windows_of_size:<l>x<w>[:<side>]  how many openings that long\n"
        "                                  and wide go through a wall: a window\n"
        "                                  in one wall of a hollow part; `:-y`\n"
        "                                  for one through the wall on -Y\n"
        "  - walls_crossed:<d>             the most separate walls any d mm\n"
        "                                  hole cuts: 1 through one wall of a\n"
        "                                  hollow part, 2 if it runs on through\n"
        "                                  the facing wall\n"
        "  - openings_apart:<d>:<s>        how many pairs of d mm openings\n"
        "                                  right through the part are s mm\n"
        "                                  apart, centre to centre\n"
        "  - hole_at:<d>:<x>,<y>,<z>       how many open d mm holes have their\n"
        "                                  axis through that point, to 0.5 mm,\n"
        "                                  in the brief's own coordinates; `*`\n"
        "                                  for one left free: hole_at:4.5:-36,*,50\n"
        "                                  for a hole along Y at X=-36, Z=50\n"
        "  - counterbores:<d>:<D>x<h>,top  how many d mm through holes are\n"
        "                                  counterbored D across, h deep, from\n"
        "                                  the top (or bottom) face\n"
        "  - standing_at:<D>x<h>:<along>,<across>  how far, in mm, a round\n"
        "                                  boss D across standing h proud is\n"
        "                                  from where the brief puts it, e.g.\n"
        "                                  standing_at:36x6:mid,mid; at_most 0.5\n"
        "  - wall_thickness:<side>, floor_thickness:<side>,\n"
        "    opening_depth:<side>          the same, for a container open on\n"
        "                                  a side other than its top: left,\n"
        "                                  right, front, back or bottom\n"
        "  - footprint_side:<mm>           the part's X or Y extent, whichever\n"
        "                                  is nearer that figure -- a side the\n"
        "                                  brief gives the whole part, which way\n"
        "                                  round it is not the brief's to say\n"
        "  - extent_side:<mm>              the part's X, Y or Z extent, whichever\n"
        "                                  is nearer -- for a part that may lie\n"
        "                                  or stand\n"
        "  - flat_extent_side:<mm>         a bent part's size laid flat -- its\n"
        "                                  length along the plate\n"
        "  - ends_round:<r>                how far, in mm, the part's two ends\n"
        "                                  along its longer side are from\n"
        "                                  semicircles of radius r, seen from\n"
        "                                  above: a strip with both ends fully\n"
        "                                  rounded; at_most 0.25\n"
        "  - flat_face:<side>              area of the part's face lying flat\n"
        "                                  on that side, in mm^2 -- which way\n"
        "                                  a dome's flat side is turned\n"
        "A requirement with a threshold and no `measurement` cannot be checked "
        "and is reported NOT_TESTED, so bind every numeric requirement you can."
    )


__all__ = [
    "MeasurementBinding",
    "MeasurementError",
    "SIMPLE_MEASUREMENTS",
    "PARAMETERISED_MEASUREMENTS",
    "SAFETY_FACTOR_KINDS",
    "MEASURED_IN",
    "is_dimensionless",
    "one_line_vocabulary",
    "parse_measurement",
    "vocabulary_help",
]
