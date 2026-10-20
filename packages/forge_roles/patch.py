"""JSON Pointer resolution and a safe subset of JSON Patch.

This module is what makes repair *surgical*. When a ForgeIR document fails to
compile, the obvious remedy is to hand the model the document and the error and
ask for a corrected document. That works, and it is the wrong shape, for three
reasons:

- It costs a full document on input and a full document on output, every attempt.
- It puts everything that was already right at risk. A model rewriting 400 lines
  to fix one field will occasionally change a fifth line too, and the diff
  nobody reads is where that lands.
- It leaves no record of *what the fix was*. A replacement document is not a
  repair, it is a new document that happens to be similar.

So repairs are expressed as pointer-targeted patches instead. The compiler's
errors already carry RFC 6901 JSON Pointers -- ``/components/0/features/3/
parameters/diameter`` -- so the diagnostic and the fix speak the same language,
the edit is minimal, and the patch itself is an auditable record of what changed
and why.

The patch subset is deliberately small: ``add``, ``remove``, ``replace``. No
``move``, no ``copy``, no ``test``. Each of those adds a way for a patch to do
something surprising, and none of them is needed to correct a malformed feature.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence

PatchOperation = Literal["add", "remove", "replace"]


class PatchError(Exception):
    """A patch could not be applied."""

    code = "RP1000_PATCH"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Mapping[str, Any] = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message}" + (f" ({rendered})" if rendered else "")


class PointerError(PatchError):
    code = "RP1001_POINTER"


def unescape_token(token: str) -> str:
    """Reverse RFC 6901 escaping. ``~1`` is ``/`` and ``~0`` is ``~``.

    Order matters: ``~01`` must decode to ``~1`` and not to ``/``, which is why
    ``~1`` is replaced before ``~0``.
    """
    return token.replace("~1", "/").replace("~0", "~")


def parse_pointer(pointer: str) -> tuple[str, ...]:
    """Split an RFC 6901 pointer into its reference tokens."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise PointerError(
            "a JSON Pointer must be empty or start with '/'", pointer=pointer
        )
    return tuple(unescape_token(token) for token in pointer.split("/")[1:])


def resolve(document: Any, pointer: str) -> Any:
    """Read the value at ``pointer``."""
    current = document
    for index, token in enumerate(parse_pointer(pointer)):
        current = _descend(current, token, pointer, index)
    return current


def exists(document: Any, pointer: str) -> bool:
    try:
        resolve(document, pointer)
    except PointerError:
        return False
    return True


def _descend(current: Any, token: str, pointer: str, index: int) -> Any:
    if isinstance(current, Mapping):
        if token not in current:
            raise PointerError(
                "pointer names a key that does not exist",
                pointer=pointer,
                token=token,
                at_segment=index,
                available=sorted(current.keys())[:20],
            )
        return current[token]
    if isinstance(current, list):
        position = _array_index(token, pointer, len(current))
        if position >= len(current):
            raise PointerError(
                "pointer names an array position past the end",
                pointer=pointer,
                token=token,
                length=len(current),
            )
        return current[position]
    raise PointerError(
        "pointer descends into a value that is neither an object nor an array",
        pointer=pointer,
        token=token,
        found_type=type(current).__name__,
    )


def _array_index(token: str, pointer: str, length: int) -> int:
    if token == "-":
        return length
    if not token.isdigit():
        raise PointerError(
            "array index in a pointer must be a non-negative integer or '-'",
            pointer=pointer,
            token=token,
        )
    return int(token)


@dataclass(frozen=True, slots=True)
class Patch:
    """One edit to a document."""

    op: PatchOperation
    pointer: str
    value: Any = None
    #: Why this edit was made. Carried into the repair record, so a reviewer can
    #: see the reasoning and not merely the diff.
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": self.op, "pointer": self.pointer}
        if self.op != "remove":
            payload["value"] = self.value
        if self.reason:
            payload["reason"] = self.reason
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Patch":
        if not isinstance(payload, Mapping):
            raise PatchError(
                "a patch is an object {op, pointer, value}",
                got=type(payload).__name__)
        op = str(payload.get("op", "")).lower()
        if op not in ("add", "remove", "replace"):
            raise PatchError(
                "unsupported patch operation",
                op=payload.get("op"),
                supported=["add", "remove", "replace"],
            )
        if "pointer" not in payload and "path" not in payload:
            raise PatchError("a patch must name a pointer", keys=sorted(payload))
        return cls(
            op=op,  # type: ignore[arg-type]
            pointer=str(payload.get("pointer", payload.get("path", ""))),
            value=payload.get("value"),
            reason=str(payload.get("reason", "")),
        )

    def render(self) -> str:
        if self.op == "remove":
            return f"remove {self.pointer}"
        rendered = _short(self.value)
        return f"{self.op} {self.pointer} = {rendered}"


def _short(value: Any, limit: int = 70) -> str:
    import json

    try:
        text = json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


#: Top-level document sections a repair may never touch, and why.
#:
#: These are the accepted record: what the part must do, what was assumed on
#: the way, who approved it, and how much risk the project carries. Everything
#: else in Forge exists to check a design against them. A repair that can edit
#: them can make any design pass, and the report still says PASS -- which is
#: strictly worse than no verification at all, because it looks checked.
#:
#: Found by audit, reproduced exactly: a single patch moved a mass threshold
#: from 8 g to 999 g; another flipped an unapproved high-risk assumption's
#: `approved` to true, which is the one thing in the system that is supposed
#: to require a human; a third deleted a requirement outright; a fourth turned
#: `at_most` into `at_least`. All five probes applied cleanly.
_THE_ACCEPTED_RECORD = ("requirements", "assumptions", "risk_class")

#: Fields that carry a human decision wherever they appear, including inside
#: a component. `approved` is a person saying yes; `state` is how a
#: requirement got into the record. Neither is geometry.
_HUMAN_DECISIONS = ("approved", "state")


def _refuse_if_it_edits_the_record(patch: Patch) -> None:
    """A repair edits the design. It never edits what the design is judged by.

    The separation this enforces is the whole premise of Forge: a deterministic
    verifier compares a model's geometry against a record the model cannot
    reach. Without it, "every gate passed" means only that the model found the
    gates inconvenient.

    Deliberately a refusal and not a silent drop. A repair that wanted to relax
    a requirement was reasoning about the wrong problem, and the analyst needs
    to be told so -- with, in the message, the thing it should have changed
    instead.
    """
    tokens = parse_pointer(patch.pointer)
    if not tokens:
        # The root pointer is refused by `_apply_one`, which owns that message.
        # Duplicating it here only changed which of two guards spoke first.
        return
    if tokens[0] in _THE_ACCEPTED_RECORD:
        raise PatchError(
            f"a repair may not change `{tokens[0]}`",
            pointer=patch.pointer,
            op=patch.op,
            section=tokens[0],
            hint=(
                f"`{tokens[0]}` is the accepted record the design is judged "
                "against, and it is not yours to edit -- relaxing a threshold, "
                "removing a requirement, or approving an assumption would make "
                "the part pass without making it right, and the report would "
                "still say PASS. Change the geometry so the requirement is "
                "met. If you believe the requirement itself is wrong, say so "
                "in your diagnosis and abandon the repair; a person decides "
                "that, not a repair round."
            ),
        )
    if tokens[-1] in _HUMAN_DECISIONS:
        raise PatchError(
            f"a repair may not set `{tokens[-1]}`",
            pointer=patch.pointer,
            op=patch.op,
            field=tokens[-1],
            hint=(
                f"`{tokens[-1]}` records a human decision. Approval is the one "
                "thing in this system that must come from a person, so a run "
                "that could grant its own would have no meaning. Leave it and "
                "fix the design; an unapproved assumption blocks release, "
                "which is the correct outcome, not a defect to patch."
            ),
        )


def pointer_by_index(document: Any, pointer: str) -> str:
    """The pointer with every array element named by its `id` turned into
    its index: `/components/0/features/corner_hole_1/parameters/entry` is
    `/components/0/features/15/parameters/entry`.

    Counting array positions is where a model's patches go wrong: an analyst
    fixing four corner holes at positions 15 to 18 wrote 16 to 19, set three
    of the four, left the first as it was, and put a counterbore's `entry`
    on the bore. A feature's id is what the model was reading; it is
    accepted as the address. Resolved against the document as the author
    saw it, before anything is applied. A token that is a number or `-`, or
    names no element, is left as written.
    """
    tokens = parse_pointer(pointer) if pointer.startswith("/") else ()
    if not tokens:
        return pointer
    current: Any = document
    out: list[str] = []
    for token in tokens:
        if isinstance(current, list) and not token.isdigit() and token != "-":
            found = [i for i, item in enumerate(current)
                     if isinstance(item, Mapping)
                     and str(item.get("id", "")) == token]
            if len(found) == 1:
                token = str(found[0])
        out.append(token)
        if isinstance(current, Mapping):
            current = current.get(token)
        elif (isinstance(current, list) and token.isdigit()
              and int(token) < len(current)):
            current = current[int(token)]
        else:
            current = None
    return "/" + "/".join(t.replace("~", "~0").replace("/", "~1") for t in out)


def pointer_by_id(document: Any, pointer: str) -> str:
    """The pointer with every array element that has an `id` named by it --
    the inverse of :func:`pointer_by_index`, so a pointer read against one
    document still finds the same element in another where it moved."""
    tokens = parse_pointer(pointer) if pointer.startswith("/") else ()
    if not tokens:
        return pointer
    current: Any = document
    out: list[str] = []
    for token in tokens:
        step = token
        if isinstance(current, list) and token.isdigit() and int(
                token) < len(current):
            item = current[int(token)]
            if isinstance(item, Mapping) and item.get("id"):
                step = str(item["id"])
            current = item
        elif isinstance(current, list):
            found = [x for x in current if isinstance(x, Mapping)
                     and str(x.get("id", "")) == token]
            current = found[0] if len(found) == 1 else None
        elif isinstance(current, Mapping):
            current = current.get(token)
        else:
            current = None
        out.append(step)
    return "/" + "/".join(t.replace("~", "~0").replace("/", "~1") for t in out)


def apply_patches(
    document: Mapping[str, Any], patches: Sequence[Patch]
) -> dict[str, Any]:
    """Apply patches in order to a deep copy, leaving the original untouched.

    All-or-nothing: if any patch fails, the exception propagates and the caller
    still holds the unmodified document. A half-applied repair would be worse
    than no repair, because the result is a document neither the model nor the
    compiler has ever seen.

    Every pointer in the batch refers to the document as the author saw it, not
    to the partially patched one; :func:`_ordered` explains how that is kept
    true and when a batch is refused for being ambiguous.

    The accepted record is checked before anything is applied, so a batch that
    mixes a legitimate geometry fix with an attempt on a requirement changes
    nothing at all -- see :func:`_refuse_if_it_edits_the_record`.
    """
    patches = [replace(p, pointer=pointer_by_index(document, p.pointer))
               for p in patches]
    # The same element removed twice -- once by its id, once by its index --
    # is one removal; applied twice it took its neighbour with it.
    seen_removals: set[str] = set()
    unique: list[Patch] = []
    for patch in patches:
        if patch.op == "remove":
            if patch.pointer in seen_removals:
                continue
            seen_removals.add(patch.pointer)
        unique.append(patch)
    patches = unique
    for patch in patches:
        _refuse_if_it_edits_the_record(patch)
    working = copy.deepcopy(dict(document))
    for patch in _ordered(patches):
        _apply_one(working, patch)
    _close_the_chain_round_what_was_removed(document, working, patches)
    return working


def _close_the_chain_round_what_was_removed(
    before: Mapping[str, Any], after: dict[str, Any], patches: Sequence[Patch]
) -> None:
    """A feature taken out of a chain: what came after it takes what it took.

    Holes are cut one after another, each from the last. An analyst removing
    one surplus pivot hole from the middle of that chain removed the hole and
    left the next one reading a feature that no longer existed; the document
    was refused, and the round was spent. Removing a step means the next step
    acts on what the removed one acted on -- for a feature with ONE input,
    that is unambiguous. With several (a boolean), nothing is guessed.
    """
    for patch in patches:
        if patch.op != "remove":
            continue
        tokens = list(parse_pointer(patch.pointer))
        if len(tokens) != 4 or tokens[0] != "components" or tokens[2] != (
                "features") or not tokens[3].isdigit():
            continue
        try:
            removed = resolve(before, patch.pointer)
            component = resolve(after, "/components/" + tokens[1])
        except PointerError:
            continue
        if not isinstance(removed, Mapping) or not isinstance(component,
                                                               Mapping):
            continue
        took = removed.get("inputs")
        name = str(removed.get("id", ""))
        if not name or not isinstance(took, list) or len(took) != 1:
            continue
        remaining = {str(f.get("id", "")) for f in component.get(
            "features", []) or [] if isinstance(f, Mapping)}
        if name in remaining:
            continue
        for feature in component.get("features", []) or []:
            inputs = feature.get("inputs") if isinstance(feature, dict) else None
            if isinstance(inputs, list) and name in inputs:
                feature["inputs"] = [took[0] if i == name else i
                                     for i in inputs]


def _ordered(patches: Sequence[Patch]) -> list[Patch]:
    """Order the batch so every pointer means what its author meant.

    A model proposing a patch set is reading one snapshot of the document, so
    every pointer in the set refers to *that* document, not to the half-patched
    one. Applying removals in the order given breaks that: deleting
    ``/features/1`` shifts ``/features/3`` down to position 2, and a batch of
    individually correct removals silently deletes the wrong feature. So
    removals within a parent array are applied last, in descending index order.

    Where that reordering could itself change the result -- an array that gets
    both a removal and another position-addressed edit in the same batch -- the
    intent is genuinely ambiguous, and it is rejected rather than resolved by a
    convention the author never agreed to. Splitting the repair into two patch
    sets makes the order explicit.
    """
    removals = [p for p in patches if p.op == "remove"]
    others = [p for p in patches if p.op != "remove"]

    shifted = {path for path, _ in map(_array_target, removals) if path is not None}
    if shifted:
        # Which combinations are actually ambiguous follows from the order
        # below, and working it out is worth the paragraph: this guard cost a
        # run a repair round it did not owe.
        #
        # Non-removals are applied FIRST, against the document exactly as the
        # author was shown it, so their indices always mean what the author
        # meant. Removals then run last, descending, so no removal renumbers a
        # later one. That leaves only two real hazards:
        #
        # * A `remove` that reaches *through* an array another removal
        #   shortens, to take a key deeper in -- `/features/2/id` after
        #   `/features/0`. The descending sort only orders siblings; this one's
        #   index 2 is stale by the time it runs.
        # * An `add` that *inserts at a numeric index* into an array a removal
        #   also addresses. The insert runs first and shifts everything after
        #   it, so the removal deletes the wrong element.
        #
        # A `replace` is neither: it runs first and swaps a value in place,
        # renumbering nothing. Rejecting a removal beside a replacement was the
        # bug -- observed live, the analyst proposed exactly that, correctly,
        # and was told to split it.
        for patch in patches:
            if patch.op == "replace":
                continue
            target, index = _array_target(patch)
            ambiguous: set[str] = set()
            if patch.op == "remove":
                # Its own slot is fine; reaching deeper through a shortened
                # array is not.
                ambiguous = _arrays_traversed(patch) & shifted
            elif patch.op == "add":
                # `_array_target` reports `-` as index -1: appending inserts
                # past the end, so it shifts nothing.
                if index is not None and index >= 0 and target in shifted:
                    ambiguous = {target}
            if ambiguous:
                raise PatchError(
                    "this patch set removes from an array that another patch "
                    "also addresses by position, so the order it is applied in "
                    "changes which element each pointer means",
                    pointer=patch.pointer,
                    array=sorted(ambiguous)[0],
                    hint="send the removals as one repair and the rest as "
                    "another, so the order is yours rather than the applier's",
                )

    removals.sort(key=_removal_sort_key, reverse=True)
    # Of the rest: replacements and keyed additions first, in the order given
    # -- none renumbers anything -- and insertions at a numeric index last,
    # from the highest index down, so no insertion moves an element another
    # patch in the set still addresses by its original position. In the
    # order given, `add .../features/2` then `replace` of what was index 5
    # (written by id) edited what had been index 4.
    # `index is not None and index >= 0`, not `index or -1`: for an insert
    # at index 0 the `or` read the zero as "no index", left it among the
    # replacements, and applied it first in the given order -- so a
    # `replace` of `/features/1` written beside it edited what had been
    # feature 0. Silently editing the wrong node is the one failure this
    # ordering exists to prevent.
    inserts = [p for p in others if p.op == "add"
               and _array_target(p)[1] is not None
               and _array_target(p)[1] >= 0]
    rest = [p for p in others if p not in inserts]
    inserts.sort(key=lambda p: (_array_target(p)[0] or "",
                                _array_target(p)[1] or 0), reverse=True)
    return rest + inserts + removals


def _array_target(patch: Patch) -> tuple[str | None, int | None]:
    """The array path and index a patch addresses, when its last token is one."""
    tokens = parse_pointer(patch.pointer)
    if not tokens:
        return (None, None)
    last = tokens[-1]
    parent = "/".join(tokens[:-1])
    if last == "-":
        return (parent, -1)
    return (parent, int(last)) if last.isdigit() else (None, None)


def _arrays_traversed(patch: Patch) -> set[str]:
    """Array paths the pointer indexes into on its way somewhere deeper.

    ``/components/0/features/2/id`` traverses ``components`` and ``features``:
    its meaning depends on both of their orderings, which is exactly what a
    removal elsewhere in one of them would change.
    """
    tokens = parse_pointer(patch.pointer)
    return {
        "/".join(tokens[:position])
        for position, token in enumerate(tokens[:-1])
        if token.isdigit() or token == "-"
    }


def _removal_sort_key(patch: Patch) -> tuple[str, int]:
    tokens = parse_pointer(patch.pointer)
    parent = "/".join(tokens[:-1])
    last = tokens[-1] if tokens else ""
    return (parent, int(last) if last.isdigit() else -1)


def _apply_one(document: dict[str, Any], patch: Patch) -> None:
    tokens = parse_pointer(patch.pointer)
    if not tokens:
        raise PatchError(
            "a patch may not replace the whole document; target a field",
            pointer=patch.pointer,
            hint="whole-document replacement is what patching exists to avoid",
        )

    parent: Any = document
    for index, token in enumerate(tokens[:-1]):
        parent = _descend(parent, token, patch.pointer, index)

    last = tokens[-1]

    if isinstance(parent, Mapping):
        if not isinstance(parent, dict):  # pragma: no cover - defensive
            raise PatchError("cannot modify an immutable mapping", pointer=patch.pointer)
        if patch.op == "remove":
            if last not in parent:
                raise PointerError(
                    "cannot remove a key that does not exist",
                    pointer=patch.pointer,
                    key=last,
                    available=sorted(parent.keys())[:20],
                )
            del parent[last]
        elif patch.op == "replace":
            if last not in parent:
                # "use 'add'" was the old advice, and it is wrong far more
                # often than it is right. Observed live: an analyst diagnosed
                # a `box` as having been given `diameter` -- it had not, the
                # diagnosis was invented -- and patched
                # `/features/0/parameters/diameter`. Told to use `add`, the
                # obedient next step is to put a `diameter` on a box, which
                # the schema then refuses. The key being absent is usually
                # evidence that the diagnosis is wrong, not that the operation
                # is, so the message says what is actually there and leaves
                # the choice to whoever reads it.
                raise PointerError(
                    f"there is no `{last}` here to replace",
                    pointer=patch.pointer,
                    key=last,
                    available=sorted(parent.keys())[:20],
                    hint=(
                        f"`{last}` is not a field of this object. What it does "
                        f"have: {', '.join(sorted(parent.keys())[:20]) or 'nothing'}. "
                        "If you expected it to be there, the diagnosis is "
                        "about a document other than this one -- re-read the "
                        "failure and patch what it actually names. Use `add` "
                        "only if this field genuinely belongs here and is "
                        "missing."
                    ),
                )
            parent[last] = patch.value
        else:
            parent[last] = patch.value
        return

    if isinstance(parent, list):
        position = _array_index(last, patch.pointer, len(parent))
        if patch.op == "add":
            if position > len(parent):
                raise PointerError(
                    "cannot insert past the end of an array",
                    pointer=patch.pointer,
                    length=len(parent),
                )
            parent.insert(position, patch.value)
        elif patch.op == "remove":
            if position >= len(parent):
                raise PointerError(
                    "cannot remove past the end of an array",
                    pointer=patch.pointer,
                    length=len(parent),
                )
            del parent[position]
        else:
            if position >= len(parent):
                raise PointerError(
                    "cannot replace past the end of an array",
                    pointer=patch.pointer,
                    length=len(parent),
                )
            parent[position] = patch.value
        return

    raise PatchError(
        "patch target's parent is neither an object nor an array",
        pointer=patch.pointer,
        found_type=type(parent).__name__,
    )


def extract_slice(
    document: Mapping[str, Any], pointers: Sequence[str], *, context: int = 1
) -> dict[str, Any]:
    """Pull out just the parts of a document the given pointers refer to.

    Used to give the Failure Analyst the minimum it needs. Sending a whole
    document to diagnose one malformed feature wastes input tokens and, more
    importantly, invites the model to comment on parts of the design nobody
    asked about.

    ``context`` walks up that many levels from each pointer, so a failure inside
    a feature's parameters yields the whole feature rather than the one bad
    field, which is usually what makes the mistake legible.
    """
    result: dict[str, Any] = {}
    for pointer in pointers:
        tokens = list(parse_pointer(pointer))
        for _ in range(context):
            if len(tokens) > 1:
                tokens.pop()
        trimmed = "/" + "/".join(tokens) if tokens else ""
        try:
            value = resolve(document, trimmed)
        except PointerError:
            continue
        result[trimmed or "/"] = value
    return result


__all__ = [
    "Patch",
    "PatchError",
    "PointerError",
    "PatchOperation",
    "apply_patches",
    "parse_pointer",
    "resolve",
    "exists",
    "extract_slice",
    "unescape_token",
]
