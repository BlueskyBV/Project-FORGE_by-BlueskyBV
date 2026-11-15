"""Answer keys: what a correct part is, written down before Forge runs.

A key states facts about the finished solid that any version of Forge can be
graded on: its overall size, its volume, its holes, its inner voids, and in
plain words everything else a correct part must have. It says nothing about
how V2 describes a part, so changing V2's spec format can never change what
counts as right (plan, section 7).

Some briefs are meant to fail. A key's ``expect`` says what a correct run
does with its brief:

- ``verified``: builds the part, and it meets every fact here;
- ``question``: asks before building, about what ``questions`` lists;
- ``cant``: refuses, because the brief contradicts itself or can't be made.

Keys are locked: a set's manifest records the SHA-256 of every key, and
:func:`verify_manifest` refuses a set whose keys changed after locking. A key
written after seeing Forge's answer would grade nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "KEY_FORMAT",
    "AnswerKey",
    "AnswerKeyError",
    "HoleFact",
    "load_key",
    "load_set",
    "lock_set",
    "verify_manifest",
]

KEY_FORMAT = 1
Expect = Literal["verified", "question", "cant"]


class AnswerKeyError(ValueError):
    """A key or manifest that is malformed or was changed after locking."""


@dataclass(frozen=True)
class HoleFact:
    """Holes of one size that go all the way through the part."""

    diameter_mm: tuple[float, float]  # the range a correct part may have
    count: int

    def __post_init__(self) -> None:
        low, high = self.diameter_mm
        if not (0 < low <= high and math.isfinite(high)):
            raise AnswerKeyError(
                f"a hole diameter range must be 0 < low <= high, got {self.diameter_mm}"
            )
        if self.count < 1:
            raise AnswerKeyError("a hole fact counts at least one hole")


@dataclass(frozen=True)
class AnswerKey:
    """The facts a correct run of one brief must meet."""

    id: str
    brief: str
    written_by: str
    independent: bool
    expect: Expect
    note: str
    envelope_mm: tuple[float, float, float] | None = None
    envelope_tolerance_mm: float = 0.2
    volume_mm3: tuple[float, float] | None = None
    through_holes: tuple[HoleFact, ...] = ()
    inner_voids: int | None = None
    facts: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    format: int = field(default=KEY_FORMAT)

    def __post_init__(self) -> None:
        if self.format != KEY_FORMAT:
            raise AnswerKeyError(f"key format {self.format} is not {KEY_FORMAT}")
        if not self.id or not self.brief.strip():
            raise AnswerKeyError("a key needs an id and its brief")
        if self.expect not in ("verified", "question", "cant"):
            raise AnswerKeyError(
                f"expect must be verified, question or cant, got {self.expect!r}"
            )
        if self.expect == "verified" and (
            self.envelope_mm is None or self.volume_mm3 is None
        ):
            raise AnswerKeyError(
                f"{self.id}: a part that should be built needs its size and volume"
            )
        if self.expect == "question" and not self.questions:
            raise AnswerKeyError(f"{self.id}: say what a good run asks about")
        envelope = self.envelope_mm
        if envelope is not None and (
            len(envelope) != 3
            or not all(math.isfinite(x) and x > 0 for x in envelope)
            or list(envelope) != sorted(envelope)
        ):
            raise AnswerKeyError(
                f"{self.id}: the envelope is three sizes, smallest first"
            )
        if self.volume_mm3 is not None:
            low, high = self.volume_mm3
            if not (0 < low <= high and math.isfinite(high)):
                raise AnswerKeyError(
                    f"{self.id}: the volume range must be 0 < low <= high"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "id": self.id,
            "brief": self.brief,
            "written_by": self.written_by,
            "independent": self.independent,
            "expect": self.expect,
            "note": self.note,
            "envelope_mm": list(self.envelope_mm) if self.envelope_mm else None,
            "envelope_tolerance_mm": self.envelope_tolerance_mm,
            "volume_mm3": list(self.volume_mm3) if self.volume_mm3 else None,
            "through_holes": [
                {"diameter_mm": list(h.diameter_mm), "count": h.count}
                for h in self.through_holes
            ],
            "inner_voids": self.inner_voids,
            "facts": list(self.facts),
            "questions": list(self.questions),
        }


def _pair(raw: Any, name: str) -> tuple[float, float] | None:
    if raw is None:
        return None
    if not (
        isinstance(raw, list)
        and len(raw) == 2
        and all(isinstance(x, (int, float)) for x in raw)
    ):
        raise AnswerKeyError(f"{name} must be [low, high]")
    return (float(raw[0]), float(raw[1]))


def key_from_dict(raw: Mapping[str, Any]) -> AnswerKey:
    try:
        envelope = raw.get("envelope_mm")
        return AnswerKey(
            id=str(raw["id"]),
            brief=str(raw["brief"]),
            written_by=str(raw["written_by"]),
            independent=bool(raw["independent"]),
            expect=raw["expect"],
            note=str(raw.get("note", "")),
            envelope_mm=tuple(float(x) for x in envelope) if envelope else None,  # type: ignore[arg-type]
            envelope_tolerance_mm=float(raw.get("envelope_tolerance_mm", 0.2)),
            volume_mm3=_pair(raw.get("volume_mm3"), "volume_mm3"),
            through_holes=tuple(
                HoleFact(
                    _pair(h["diameter_mm"], "diameter_mm") or (0.0, 0.0),
                    int(h["count"]),
                )
                for h in raw.get("through_holes", ())
            ),
            inner_voids=raw.get("inner_voids"),
            facts=tuple(str(f) for f in raw.get("facts", ())),
            questions=tuple(str(q) for q in raw.get("questions", ())),
            format=int(raw.get("format", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AnswerKeyError):
            raise
        raise AnswerKeyError(f"malformed key: {exc}") from exc


def _canonical(key: AnswerKey) -> bytes:
    return (json.dumps(key.as_dict(), indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def load_key(path: Path) -> AnswerKey:
    return key_from_dict(json.loads(path.read_text(encoding="utf-8")))


def lock_set(directory: Path, keys: Sequence[AnswerKey], name: str) -> str:
    """Write every key and a manifest of their SHA-256; return the manifest's own hash."""
    ids = [k.id for k in keys]
    if len(set(ids)) != len(ids):
        raise AnswerKeyError("key ids must be unique")
    directory.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for key in keys:
        data = _canonical(key)
        (directory / f"{key.id}.json").write_bytes(data)
        hashes[f"{key.id}.json"] = hashlib.sha256(data).hexdigest()
    manifest = {"set": name, "format": KEY_FORMAT, "keys": hashes}
    body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (directory / "MANIFEST.json").write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def verify_manifest(directory: Path) -> dict[str, AnswerKey]:
    """Load a locked set, refusing any key that changed or went missing."""
    manifest = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    loaded: dict[str, AnswerKey] = {}
    for filename, digest in sorted(manifest["keys"].items()):
        path = directory / filename
        if not path.exists():
            raise AnswerKeyError(f"{filename} is in the manifest but missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise AnswerKeyError(f"{filename} changed after the set was locked")
        key = load_key(path)
        loaded[key.id] = key
    extra = (
        {p.name for p in directory.glob("*.json")}
        - set(manifest["keys"])
        - {"MANIFEST.json"}
    )
    if extra:
        raise AnswerKeyError(f"keys not in the manifest: {sorted(extra)}")
    return loaded


def load_set(directory: Path) -> dict[str, AnswerKey]:
    """The keys of a locked set (alias of :func:`verify_manifest`)."""
    return verify_manifest(directory)
