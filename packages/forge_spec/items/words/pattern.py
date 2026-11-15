"""How the spec's words say each pattern mode: the ``words`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_WORDS` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from forge_registry import Registry

from forge_spec.draft import PATTERN_FIELDS


class PatternWords:
    """One pattern mode, as the spec's words say it."""

    #: The mode this entry is for.
    key = ""
    #: What the mode means, as the spec writer's guide says it.
    meaning = ""
    #: Its copies are placed by its circle's centre (a circle's, an arc's).
    placed_by_circle = False

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        """Its copies in words: ``v`` and ``n`` its values and counts, ``axis`` its axis as said, ``named`` its values starting with a prefix, by axis."""
        raise NotImplementedError(self.key)


class Corners(PatternWords):
    key = "corners"
    meaning = "one copy at each corner of a rectangular face, centres inset_<axis> in from its edges"

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        return f"one at each corner, centres in from the edges by {named('inset_')}"


class Rectangle(PatternWords):
    key = "rectangle"
    meaning = "copies at the four corners of a rectangle <x> by <y> (the face's axes), centred where place puts it; measured from an edge, place is to the nearest copy"

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        return f"at the corners of a rectangle {named('')}"


class Ends(PatternWords):
    key = "ends"
    meaning = "two copies along axis, centres inset in from each end of the face"

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        from forge_spec.items.words._common import _v

        return f"one near each end along {axis}, centres {_v(v.get('inset'))} in from the ends"


class Row(PatternWords):
    key = "row"
    meaning = "count copies in a row along axis, pitch apart; centred or offset, place puts the row's centre, and from an edge it is measured to the nearest copy (“the first hole 5 mm from the end”)"

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        from forge_spec.items.words._common import _v

        return f"{_v(n.get('count'))} in a row along {axis}, {_v(v.get('pitch'))} apart"


class Grid(PatternWords):
    key = "grid"
    meaning = "count_<a> by count_<b> copies, pitch_<a> and pitch_<b> apart; centred or offset, place puts the grid's centre, and from an edge it is measured to the nearest copy"

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        return f"a grid: counts {named('count_')}; pitches {named('pitch_')}"


class RoundWords(PatternWords):
    """A circle's or an arc's copies: on a circle of its diameter, or round a rod's side."""

    placed_by_circle = True

    def spacing(self, v: Mapping[str, object]) -> str:
        raise NotImplementedError(self.key)

    def said(
        self,
        v: Mapping[str, object],
        n: Mapping[str, object],
        axis: str,
        named: Callable[[str], str],
    ) -> str:
        from forge_spec.items.words._common import _v

        if "diameter" in v:
            where = f" on a {_v(v['diameter'])} circle"
            start = _v(v["start"]) if "start" in v else "0 deg (assumed)"
        elif (
            "start" in v
        ):  # on a round side the circle is the side; or the spec is faulty
            where, start = " round the axis, with no circle size", _v(v["start"])
        else:
            where, start = " round the side", "the angle above"
        spacing = self.spacing(v)
        return f"{_v(n.get('count'))} {spacing}{where}, the first at {start}"


class Circle(RoundWords):
    key = "circle"
    meaning = "count copies equally spaced round a circle of diameter, the first at start (from the face's first axis towards its second), placed by the circle's centre; round a rod's side, give count only"

    def spacing(self, v: Mapping[str, object]) -> str:
        return "equally spaced"


class Arc(RoundWords):
    key = "arc"
    meaning = "like circle, but step apart (“two holes 90 degrees apart”); round a rod's side, count and step"

    def spacing(self, v: Mapping[str, object]) -> str:
        from forge_spec.items.words._common import _v

        return f"{_v(v.get('step'))} apart"


PATTERN_WORDS: Registry[PatternWords] = Registry(
    "forge_spec.words.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternWords,
)
