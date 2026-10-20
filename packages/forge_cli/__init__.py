"""forge_cli - the ``forge`` command line interface.

Exit codes follow the release verdict, and the distinction matters in CI:

==== ==========================================================
0    PASS -- every critical gate passed
1    FAIL -- at least one critical gate failed
2    Undecided: BLOCKED, INCONCLUSIVE or NOT_TESTED
==== ==========================================================

Code 2 exists so that "we could not check" cannot be scripted as success. A
pipeline that treats any non-zero code as a failure will stop, which is correct;
one that treats only 1 as a failure would let an unverified design through, and
that is the outcome this whole system is built to prevent.
"""

from __future__ import annotations

from .cli import EXIT_FAIL, EXIT_PASS, EXIT_UNDECIDED, build_parser, main

__version__ = "0.1.0"
__all__ = [
    "main",
    "build_parser",
    "EXIT_PASS",
    "EXIT_FAIL",
    "EXIT_UNDECIDED",
    "__version__",
]
