"""What can go wrong building with OpenCascade, each failure naming where it happened.

Every error carries a code, a message a person can act on, and the detail of
where it happened: the component, the step, the operation and the step's
JSON pointer, as V1's compile errors do, so a failure names a spec item
through the step's ``for_items`` (docs/V2-stage3.md, section 7.1).

>>> error = DesignError("a cone needs a height", step="s3", op="cone")
>>> str(error)
"[OC1300_DESIGN] a cone needs a height (op='cone', step='s3')"
>>> error.as_dict()["detail"]["step"]
's3'
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AfterCheckError",
    "BooleanFlagError",
    "DesignError",
    "InvalidResultError",
    "KernelMissingError",
    "OccError",
    "OperationError",
    "RefError",
    "UnsupportedOpError",
]


class OccError(Exception):
    """A step could not be built as asked. The build stops here (it fails closed)."""

    code = "OC1000_OCC"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, Any] = dict(detail)

    def where(self, **detail: Any) -> OccError:
        """The same error, with where it happened filled in (what it already says is kept)."""
        for key, value in detail.items():
            self.detail.setdefault(key, value)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        if not self.detail:
            return f"[{self.code}] {self.message}"
        shown = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message} ({shown})"


class KernelMissingError(OccError):
    """The exact kernel isn't installed, or is a version Forge wasn't built for."""

    code = "OC1001_KERNEL_MISSING"


class OperationError(OccError):
    """OpenCascade refused the operation, or raised while doing it."""

    code = "OC1100_OPERATION"


class BooleanFlagError(OccError):
    """A boolean reported an error, or a warning that isn't allowed."""

    code = "OC1101_BOOLEAN_FLAG"


class InvalidResultError(OccError):
    """The operation finished, and what it made isn't a valid solid."""

    code = "OC1102_INVALID"


class AfterCheckError(OccError):
    """The operation finished with a valid solid that isn't what it should have made."""

    code = "OC1200_AFTER_CHECK"


class DesignError(OccError):
    """The parameters ask for something that can't exist (V1 refuses it too)."""

    code = "OC1300_DESIGN"


class RefError(OccError):
    """A reference's match condition failed: what was found is listed, nothing is guessed."""

    code = "OC1400_REFERENCE"


class UnsupportedOpError(OccError):
    """The document asks for an operation the exact kernel doesn't build."""

    code = "OC1500_UNSUPPORTED"
