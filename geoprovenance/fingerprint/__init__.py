"""Dataset fingerprinting — Person B.

Research doc §4.3 Layer 3 and §6.4. Computes the SHA-256 that Person C's
"has this input changed?" audit compares against, and that RQ3 measures.

Imports no QGIS: a fingerprint needs a file path and nothing else, so this
whole layer is verifiable with `make test` on a machine with no GIS stack.
"""

from .compare import (
    VERDICT_ATTRIBUTES_CHANGED,
    VERDICT_CHANGED,
    VERDICT_GEOMETRY_CHANGED,
    VERDICT_RESAVED,
    VERDICT_SCHEMA_CHANGED,
    VERDICT_UNCHANGED,
    VERDICT_UNKNOWN,
    Comparison,
    compare_fingerprint_sets,
)
from .hash import (
    ATTRIBUTES_ALGORITHM,
    COMPLEMENTARY_STRATEGIES,
    GEOMETRY_ALGORITHM,
    HASH_ALGORITHM,
    KNOWN_STRATEGIES,
    LARGE_FILE_THRESHOLD_BYTES,
    PRIMARY_STRATEGIES,
    STRATEGY_ATTRIBUTES,
    STRATEGY_FILE,
    STRATEGY_GEOMETRY,
    STRATEGY_SCHEMA_SAMPLE,
    STRATEGY_STRUCTURE,
    STRUCTURE_ALGORITHM,
    Fingerprint,
    FingerprintError,
    can_fingerprint,
    complementary_fingerprints,
    fingerprint_dataset,
    fingerprint_file,
    sha256_file,
)
from .readers import (
    DatasetDescription,
    DatasetReadError,
    LayerDescription,
    describe,
    sidecar_paths,
)

__all__ = [
    "ATTRIBUTES_ALGORITHM",
    "COMPLEMENTARY_STRATEGIES",
    "Comparison",
    "DatasetDescription",
    "DatasetReadError",
    "Fingerprint",
    "FingerprintError",
    "GEOMETRY_ALGORITHM",
    "HASH_ALGORITHM",
    "KNOWN_STRATEGIES",
    "LARGE_FILE_THRESHOLD_BYTES",
    "LayerDescription",
    "PRIMARY_STRATEGIES",
    "STRATEGY_ATTRIBUTES",
    "STRATEGY_FILE",
    "STRATEGY_GEOMETRY",
    "STRATEGY_SCHEMA_SAMPLE",
    "STRATEGY_STRUCTURE",
    "STRUCTURE_ALGORITHM",
    "VERDICT_ATTRIBUTES_CHANGED",
    "VERDICT_CHANGED",
    "VERDICT_GEOMETRY_CHANGED",
    "VERDICT_RESAVED",
    "VERDICT_SCHEMA_CHANGED",
    "VERDICT_UNCHANGED",
    "VERDICT_UNKNOWN",
    "can_fingerprint",
    "compare_fingerprint_sets",
    "complementary_fingerprints",
    "describe",
    "fingerprint_dataset",
    "fingerprint_file",
    "sha256_file",
    "sidecar_paths",
]
