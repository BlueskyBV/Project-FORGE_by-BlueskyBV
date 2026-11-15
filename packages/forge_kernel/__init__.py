"""forge_kernel - lineage-addressed topology and incremental compilation.

Two ideas live here, and they are the two that make the rest of Forge possible.

**Lineage-addressed topology.** The identity of a named piece of geometry is a
hash of the *construction* that produced it, never of its coordinates or its
index in a rebuilt topology. Change a parameter and every token is bit-for-bit
identical, so every selection still resolves -- not because a matcher found the
face again, but because nothing about its identity depended on the geometry.
Change the topology so that a named face is buried, and the reference fails with
a diagnostic naming the entity and the feature that consumed it. Stable by
construction, loudly broken when it should be. See :mod:`forge_kernel.lineage`.

**Content-addressed incremental compilation.** The feature graph is compiled the
way a build system builds a source tree: each node is keyed by its kind, its
resolved parameters, its inputs' hashes and the backend's identity, and only
nodes whose key changed are rebuilt. An optimiser varying one dimension over
hundreds of candidates rebuilds the dirty cone and reuses the rest. See
:mod:`forge_kernel.cache`.

>>> from forge_ir import Document
>>> from forge_kernel import Compiler
>>> doc = Document.from_json(open("examples/clevis/clevis.forgeir.json").read())
>>> compiler = Compiler()
>>> part = compiler.compile_component(doc.component("clevis"))
>>> part.geometry_map.resolve("pivot.bore").dimensions["radius"]
4.1
"""

from __future__ import annotations

from .cache import (
    CACHE_SCHEME_VERSION,
    CacheStatistics,
    ContentCache,
    content_hash,
    feature_hash,
)
from .compiler import (
    CompiledPart,
    CompileError,
    Compiler,
    FeatureTrace,
    backend_capabilities,
    compile_component,
    compile_products,
    resolve_feature_parameters,
)
from .implicit_backend import (
    BACKEND_IDENTITY,
    BackendError,
    BuildContext,
    UnsupportedFeatureError,
    builder_for,
    supported_kinds,
)
from .lineage import (
    LINEAGE_SCHEME_VERSION,
    EntityStatus,
    Frame,
    SelectionError,
    SemanticEntity,
    SemanticGeometryMap,
    derived_token,
    lineage_token,
    validate_entities,
)
from .products import (
    DatumAxisProduct,
    DatumPlaneProduct,
    DatumPointProduct,
    Product,
    ProfileProduct,
    SolidProduct,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Compiler",
    "CompiledPart",
    "FeatureTrace",
    "CompileError",
    "compile_component",
    "compile_products",
    "resolve_feature_parameters",
    "backend_capabilities",
    "lineage_token",
    "derived_token",
    "LINEAGE_SCHEME_VERSION",
    "EntityStatus",
    "Frame",
    "SemanticEntity",
    "SemanticGeometryMap",
    "SelectionError",
    "validate_entities",
    "ContentCache",
    "CacheStatistics",
    "content_hash",
    "feature_hash",
    "CACHE_SCHEME_VERSION",
    "BACKEND_IDENTITY",
    "BuildContext",
    "BackendError",
    "UnsupportedFeatureError",
    "builder_for",
    "supported_kinds",
    "Product",
    "SolidProduct",
    "ProfileProduct",
    "DatumPlaneProduct",
    "DatumAxisProduct",
    "DatumPointProduct",
]
