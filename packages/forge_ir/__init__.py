"""forge_ir - the canonical engineering design language.

ForgeIR is the format of record for a design. Every CAD application Forge talks
to -- OpenCascade, the implicit screening kernel, Autodesk Fusion -- is a backend
that consumes it. None of them is privileged, and none of their idioms leak into
the language.

What the language guarantees
----------------------------
*Every dimensional value carries a unit.* The decoder refuses a bare number
where a length belongs, so a missing unit is a validation error rather than a
silent assumption about millimetres.

*Every error names a location.* Failures carry an RFC 6901 JSON Pointer --
``/components/0/features/3/parameters/diameter`` -- so a repair strategy can act
on the offending node without being shown, or being able to corrupt, the rest of
the document.

*Unknown fields are refused, not ignored.* A misspelled field that is silently
dropped is the worst available outcome: the document looks accepted and the
intent is gone. Extensions use the reserved ``x_`` prefix.

*Geometry is referenced by meaning.* A feature publishes named outputs -- a hole
publishes ``pivot.bore`` and ``pivot.axis`` -- and interfaces, mates, loads and
mesh groups refer to those names. Nothing anywhere stores a face index.

>>> from forge_ir import Document
>>> doc = Document.from_json(open("examples/clevis/clevis.forgeir.json").read())
>>> doc.component("clevis_base").body_feature
'body'
"""

from __future__ import annotations

from .document import (
    SCHEMA_VERSION,
    Assumption,
    Component,
    Document,
    Interface,
    InterfaceType,
    Provenance,
    Requirement,
    RequirementState,
    RequirementStrength,
    RequirementType,
    RiskClass,
    Units,
    VerificationMethod,
    decode_assumption,
    decode_component,
    decode_document,
    decode_interface,
    decode_parameter,
    decode_requirement,
)
from .features import (
    FEATURE_KINDS,
    FEATURE_SPECS,
    Feature,
    FeatureGraph,
    FeatureSpec,
    ParameterSort,
    ParameterSpec,
    ProductKind,
    SemanticOutput,
    decode_feature,
    decode_feature_graph,
    feature_spec,
)
from .measurements import (
    MeasurementBinding,
    MeasurementError,
    parse_measurement,
    vocabulary_help,
)
from .spec import (
    AUTHORING_RULES,
    authoring_guide,
    available_units,
    document_schema,
    feature_catalogue,
    write_schema,
)
from .schema import (
    DanglingReferenceError,
    DuplicateIdentifierError,
    MissingFieldError,
    Reader,
    SchemaError,
    SchemaErrorGroup,
    TypeMismatchError,
    UnknownFieldError,
    ValueRangeError,
    join_pointer,
)
from .values import (
    CountValue,
    EnumValue,
    ExpressionValue,
    FlagValue,
    IRValue,
    QuantityValue,
    ScalarValue,
    VectorValue,
    decode_scalar,
    decode_value,
    decode_vector,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    # document
    "Document",
    "Component",
    "Interface",
    "Requirement",
    "Assumption",
    "Units",
    "Provenance",
    "RiskClass",
    "InterfaceType",
    "RequirementType",
    "RequirementStrength",
    "RequirementState",
    "VerificationMethod",
    "decode_document",
    "decode_component",
    "decode_interface",
    "decode_requirement",
    "decode_assumption",
    "decode_parameter",
    # features
    "Feature",
    "FeatureGraph",
    "FeatureSpec",
    "ParameterSpec",
    "SemanticOutput",
    "ProductKind",
    "ParameterSort",
    "FEATURE_SPECS",
    "FEATURE_KINDS",
    "feature_spec",
    "decode_feature",
    "decode_feature_graph",
    # values
    "QuantityValue",
    "ExpressionValue",
    "VectorValue",
    "EnumValue",
    "FlagValue",
    "CountValue",
    "ScalarValue",
    "IRValue",
    "decode_scalar",
    "decode_vector",
    "decode_value",
    # schema
    "Reader",
    "SchemaError",
    "SchemaErrorGroup",
    "MissingFieldError",
    "TypeMismatchError",
    "UnknownFieldError",
    "ValueRangeError",
    "DuplicateIdentifierError",
    "DanglingReferenceError",
    "join_pointer",
    # model-facing contract
    "AUTHORING_RULES",
    "authoring_guide",
    "feature_catalogue",
    "document_schema",
    "write_schema",
    "available_units",
    "MeasurementBinding",
    "MeasurementError",
    "parse_measurement",
    "vocabulary_help",
]
