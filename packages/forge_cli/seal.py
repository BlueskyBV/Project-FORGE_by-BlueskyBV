"""A person's confirmation, sealed (docs/V2-stage4.md, 9.7).

A spec's digest proves it unchanged since it was locked, not who confirmed
it: anyone can write ``"by": "person"`` and hash again. So when a person
confirms a spec in Forge's own window (rule R12), ``forge spec`` seals the
digest with this installation's key, an HMAC-SHA256, and writes the seal
beside it; ``forge build`` takes a person's confirmation only with a seal
its own key makes, and builds any other as a draft.

The key is made once, from the operating system's random source, and kept
in the user's own Forge folder (``~/.forge/confirm.key``), readable by the
user alone where the system allows it: never in a run's folder, never
printed. A program with the user's files can still read it: the seal stops
a confirmation written without Forge's window, not one forged by a program
that already owns the user's account.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["KEY_FILE", "SealError", "Sealer", "forge_folder"]

#: The key's file, in the user's own Forge folder.
KEY_FILE = "confirm.key"
#: The key's length, in bytes.
_KEY_BYTES = 32
#: What a seal is of: the digest, under a name of its own, so a seal can't be taken for any other HMAC.
_PURPOSE = "forge spec confirmed by a person, v1: "


class SealError(OSError):
    """The key can't be made or read."""


def forge_folder() -> Path:
    """The user's own Forge folder: ``.forge`` in their home folder."""
    return Path.home() / ".forge"


@dataclass(frozen=True)
class Sealer:
    """This installation's key, to seal a digest and to tell a seal it made."""

    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.key) != _KEY_BYTES:
            raise SealError(f"a confirmation key is {_KEY_BYTES} bytes")

    @classmethod
    def of_install(cls, folder: Path | None = None, *, create: bool) -> Sealer | None:
        """The key in ``folder`` (the user's Forge folder by default); made there when ``create`` and there is none, else None."""
        path = (folder if folder is not None else forge_folder()) / KEY_FILE
        if path.exists():
            try:
                text = path.read_text(encoding="ascii").strip()
                return cls(bytes.fromhex(text))
            except (OSError, ValueError, UnicodeError) as error:
                raise SealError(
                    f"the confirmation key at {path} can't be read: {error}"
                ) from None
        if not create:
            return None
        key = secrets.token_bytes(_KEY_BYTES)
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(handle, "w", encoding="ascii") as out:
                out.write(key.hex() + "\n")
        except FileExistsError:
            # Made at the same moment by another run: that one's is the key.
            return cls.of_install(folder, create=False)
        except OSError as error:
            raise SealError(
                f"the confirmation key can't be made at {path}: {error}"
            ) from None
        return cls(key)

    def seal(self, digest: str) -> str:
        """The seal of a confirmed spec's digest."""
        return hmac.new(
            self.key, (_PURPOSE + digest).encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def holds(self, digest: str, seal: object) -> bool:
        """Whether ``seal`` is this key's seal of ``digest`` (compared in constant time)."""
        if not isinstance(seal, str):
            return False
        return hmac.compare_digest(
            self.seal(digest).encode("ascii"), seal.encode("utf-8", "replace")
        )
