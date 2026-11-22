"""A spec's schema version, and the migrations between versions (ADR-0026; V2-stage4b-0c.md, 3.2).

Every draft says the version of the schema it is written in:
``"schema_version": "1.1"``, a major and a minor number. A minor version
only adds optional fields, so a draft of an earlier minor version of the
same major reads as it is. A major version changes what fields mean, and
reaching it from the major before is a **migration**: a pure function from
a draft's JSON at one major version to the next, kept forever in
:mod:`.migrations` and proven on every draft Forge holds (the migrated
draft on the new code against the old draft on the old: the same shape and
checks). A spec is read in the current version, whatever version its draft
was written in; a spec locked in an earlier one keeps that version with its
lock (:mod:`.lock`). Specs drafted before versions said
``"spec_format": 1``, which is version 1.0.

The versions: 1.0, ``spec_format`` 1; 1.1, named ``schema_version``;
1.2, a placement's ``turn`` on a flat face; 1.3, a hole's, a boss's or a
post's ``tilt`` and ``tilt_towards`` on a flat face; 1.4, positions and
choices along a flat face's own axes ``u`` and ``v``, and the far face of a
turned item; 1.5, a block's and a cylinder's ``tilt`` and ``tilt_towards``
on a flat face (a body leaning as a post or a boss does); 1.6, a
placement's ``latitude`` on a ball's or a dome's surface; 1.7, a cut's
``depth`` through all, ``{"through_all": true}``, or up to a face,
``{"up_to": {...}, "offset": size}``; 1.8, through the next face,
``{"through_next": true}``, with how deep the preview found it ``reaches``;
1.9, a hexagonal pocket, ``"shape": "hexagon"`` with its ``across_flats``,
and a pocket of any outline, ``"shape": "profile"`` with its ``profile``;
1.10, ``unable``: what the brief asks that no kind makes yet (gear teeth),
said instead of drafting a stand-in for it; 1.11, ``requirements.limits``:
the brief's limits on the whole part, its mass and how tall, long or wide
it is, checked on the built part.

>>> version_of({"schema_version": "1.1"})
(1, 1)
>>> version_of({"spec_format": 1})
(1, 0)
>>> migrate({"spec_format": 1, "name": "p", "items": []})[1:]
((1, 0), ())
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .migrations import STEPS, Migration

__all__ = [
    "CURRENT",
    "MIGRATIONS",
    "Version",
    "VersionError",
    "migrate",
    "version_of",
    "written",
]

Version = tuple[int, int]

#: The version Forge writes, and the latest it reads.
CURRENT: Version = (1, 11)

#: The major steps, in order: (from this major version, to the next, the migration), from :mod:`.migrations`.
MIGRATIONS: tuple[tuple[int, int, Migration], ...] = STEPS

_VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")


class VersionError(ValueError):
    """A draft whose version Forge can't read: none, a malformed one, or one written for a newer Forge.

    ``field`` is the draft's field at fault.
    """

    def __init__(self, message: str, field: str = "schema_version") -> None:
        super().__init__(message)
        self.field = field


def written(version: Version) -> str:
    """A version as a draft writes it: "1.1"."""
    return f"{version[0]}.{version[1]}"


def version_of(raw: Mapping[str, Any]) -> Version:
    """The version a draft says it is written in."""
    new, old = "schema_version" in raw, "spec_format" in raw
    if new and old:
        raise VersionError(
            "a draft gives its schema_version, not a spec_format as well", "spec_format"
        )
    if new:
        text = raw["schema_version"]
        found = _VERSION.fullmatch(text) if isinstance(text, str) else None
        if found is None:
            number = isinstance(text, (int, float)) and not isinstance(text, bool)
            raise VersionError(
                "schema_version is a major and a minor number written as text, in quotes: "
                f'"{written(CURRENT)}"' + (f", not the number {text}" if number else "")
            )
        return int(found.group(1)), int(found.group(2))
    if old:
        if type(raw["spec_format"]) is not int or raw["spec_format"] != 1:
            raise VersionError(
                f'spec_format is 1, or give the schema_version, "{written(CURRENT)}"',
                "spec_format",
            )
        return (1, 0)
    raise VersionError(f'give the draft\'s schema_version, "{written(CURRENT)}"')


def migrate(raw: Mapping[str, Any]) -> tuple[dict[str, Any], Version, tuple[str, ...]]:
    """A draft brought to the current major version: (the draft, the version it was written in, each migration made).

    The draft keeps its own version field until a migration rewrites it; a
    draft of the current major version comes back as it is. A version newer
    than this Forge's is refused, never guessed at.
    """
    version = version_of(raw)
    if version[0] > CURRENT[0] or (
        version[0] == CURRENT[0] and version[1] > CURRENT[1]
    ):
        raise VersionError(
            f"the draft is written for a newer Forge (schema_version {written(version)}); "
            f"this one reads up to {written(CURRENT)}"
        )
    draft = dict(raw)
    made: list[str] = []
    major = version[0]
    for source, target, step in MIGRATIONS:
        if source == major:
            draft = step(draft)
            made.append(
                f"{source}.x to {target}.0: {(step.__doc__ or step.__name__).splitlines()[0]}"
            )
            major = target
    return draft, version, tuple(made)
