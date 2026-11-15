"""forge_spec - the PartSpec: what the part is, confirmed by a person.

The spec is V2's contract (ADR-0013). The model drafts it, citing the brief's
words for every value; Forge checks it with deterministic code; the person
confirms it; and from then on it is locked, and everything downstream is
judged against it.

This package is part of the trust core: it imports only the standard library,
NumPy and other trust-core packages, and no model or CAD library (ADR-0002).

Built so far (stage 1):

- :mod:`~forge_spec.words`: the brief, numbered word by word;
- :mod:`~forge_spec.citations`: does a value follow from the words it cites;
- :mod:`~forge_spec.values`: values, counts and their provenance;
- :mod:`~forge_spec.accounting`: nothing in the brief may quietly disappear;
- :mod:`~forge_spec.problems`: faults collected item by item, in one round;
- :mod:`~forge_spec.schema`: every item kind, declared once;
- :mod:`~forge_spec.draft` and :mod:`~forge_spec.wire`: a draft read into
  typed items, and written back;
- :mod:`~forge_spec.tables` and :mod:`~forge_spec.derived`: values looked up
  or worked out, checked like values read;
- :mod:`~forge_spec.placement`: stated relations to positions, and only those;
- :mod:`~forge_spec.checks`: everything code can settle before anyone looks;
- :mod:`~forge_spec.render`: the fixed wording the person confirms;
- :mod:`~forge_spec.lock`: the confirmed spec, locked by its hash.
"""

from __future__ import annotations

from .accounting import FUNCTION_WORDS, Accounting, account
from .checks import SpecProblem, SpecReport, check_draft
from .citations import (
    CitationCheck,
    Follows,
    Reading,
    Slot,
    check_count,
    check_quantity,
    is_numeric_word,
    numeric_at,
    readings,
    slot_count,
    unit_of_word,
)
from .derived import FormulaCheck, check_formula
from .draft import SPEC_FORMAT, Item, PartSpec, read_draft
from .lock import ConfirmedSpec, LockError, lock, spec_digest, unlock
from .placement import Layout, solve
from .problems import Problem, Problems, pointer
from .render import RenderedSpec, render
from .schema import KINDS, KindSpec, kind_spec
from .tables import lookup_fit, table_value
from .values import (
    Count,
    Provenance,
    Source,
    Tolerance,
    Value,
    check_citation,
    read_count,
    read_provenance,
    read_value,
)
from .wire import to_wire
from .words import NumberedBrief, Sentence, Word, WordRef, number_words

__all__ = [
    "FUNCTION_WORDS",
    "KINDS",
    "SPEC_FORMAT",
    "Accounting",
    "CitationCheck",
    "ConfirmedSpec",
    "Count",
    "Follows",
    "FormulaCheck",
    "Item",
    "KindSpec",
    "Layout",
    "LockError",
    "NumberedBrief",
    "PartSpec",
    "Problem",
    "Problems",
    "Provenance",
    "Reading",
    "RenderedSpec",
    "Sentence",
    "Slot",
    "Source",
    "SpecProblem",
    "SpecReport",
    "Tolerance",
    "Value",
    "Word",
    "WordRef",
    "account",
    "check_citation",
    "check_count",
    "check_draft",
    "check_formula",
    "check_quantity",
    "is_numeric_word",
    "kind_spec",
    "lock",
    "lookup_fit",
    "number_words",
    "numeric_at",
    "pointer",
    "read_count",
    "read_draft",
    "read_provenance",
    "read_value",
    "readings",
    "render",
    "slot_count",
    "solve",
    "spec_digest",
    "table_value",
    "to_wire",
    "unit_of_word",
    "unlock",
]
