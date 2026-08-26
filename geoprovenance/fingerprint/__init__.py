"""Dataset fingerprinting — Person B.

Research doc §4.3 Layer 3 and §6.4. Computes the SHA-256 that Person C's
"has this input changed?" audit compares against, and that RQ3 measures.

Imports no QGIS: a fingerprint needs a file path and nothing else, so this
whole layer is verifiable with `make test` on a machine with no GIS stack.
"""

from .hash import (
    HASH_ALGORITHM,
    LARGE_FILE_THRESHOLD_BYTES,
    STRATEGY_FILE,
    STRATEGY_SCHEMA_SAMPLE,
    Fingerprint,
    FingerprintError,
    can_fingerprint,
    fingerprint_file,
    sha256_file,
)

__all__ = [
    "HASH_ALGORITHM",
    "LARGE_FILE_THRESHOLD_BYTES",
    "STRATEGY_FILE",
    "STRATEGY_SCHEMA_SAMPLE",
    "Fingerprint",
    "FingerprintError",
    "can_fingerprint",
    "fingerprint_file",
    "sha256_file",
]
