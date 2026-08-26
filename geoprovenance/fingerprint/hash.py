"""SHA-256 dataset fingerprinting, with the §6.4 tiered fallback.

Owner: Person B.  Research doc §4.3 Layer 3, §6.4.

    RULES.md §2.2 — standard library only. `hashlib` and `pathlib`, nothing else.
    RULES.md §1.3 — this module computes; it never writes. The caller hands the
    result to `ProvenanceStore.add_fingerprint()`.

Two strategies, chosen by file size (research doc §6.4):

    file            SHA-256 over every byte. Exact: any change to the file is
                    detected. The default, and what every dataset under the
                    threshold gets.
    schema_sample   For files too large to read end to end inside a user's
                    processing run. Hashes the shape of the data — size,
                    feature count, field names — instead of its bytes.
                    Approximate by construction: it can miss an edit that
                    preserves all three. That is a stated §6.4 trade-off, and
                    `hash_strategy` records which one was used so Person C's
                    audit can report the weaker guarantee rather than imply
                    the stronger one.

Why the threshold is a parameter and not a constant read at call time: RQ3
measures change-detection accuracy, and an experiment that cannot vary the
threshold cannot show where the fallback starts costing accuracy.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Sequence

#: Written into `fingerprints.hash_algorithm`. The column defaults to this too.
HASH_ALGORITHM = "SHA-256"

#: research doc §6.4 — "<1s for <500MB" is the measured basis for full hashing.
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024

#: `fingerprints.hash_strategy` values. Person A's schema column, B's vocabulary.
STRATEGY_FILE = "file"
STRATEGY_SCHEMA_SAMPLE = "schema_sample"

#: Read size for the streaming hash. 1 MiB keeps a 1 GB raster off the heap
#: while staying far above the syscall overhead of a smaller buffer.
_CHUNK_BYTES = 1024 * 1024


class FingerprintError(RuntimeError):
    """A fingerprint was asked for that cannot be computed as asked."""


@dataclass(frozen=True)
class Fingerprint:
    """One computed fingerprint, shaped to `ProvenanceStore.add_fingerprint`.

    `feature_count` is carried through rather than derived: it arrives on the
    capture event, which read it from the layer QGIS already had open. Opening
    the file again here to recount would cost a second read of the data and
    would need a format reader this layer deliberately does not have.
    """

    hash_value: str
    hash_strategy: str
    file_size_bytes: int
    feature_count: int | None = None
    hash_algorithm: str = HASH_ALGORITHM

    def as_store_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for `ProvenanceStore.add_fingerprint()`.

        `computed_at` is deliberately absent — the store defaults it to a
        microsecond-precision timestamp, which is what
        `fingerprints UNIQUE(entity_id, hash_strategy, computed_at)` needs when
        one file is re-measured inside the same second (CONTRACT_schema.md
        decision 4). Supplying a coarser one here is how that constraint fires.

        `hash_strategy` IS included, and matters: it is part of that key, so
        two complementary measurements of one file are kept apart by the
        method rather than by whether the clock happened to tick between them.
        """
        return {
            "hash_value": self.hash_value,
            "hash_algorithm": self.hash_algorithm,
            "hash_strategy": self.hash_strategy,
            "file_size_bytes": self.file_size_bytes,
            "feature_count": self.feature_count,
        }


def can_fingerprint(path: str | pathlib.Path | None) -> bool:
    """Whether `path` is something this layer can hash at all.

    False for memory and temporary layers, which reach Person B as
    `"path": None` with `layer_type` still set (CONTRACT_event.md rule 1).
    There is no file on disk, so there is nothing to hash — and a missing
    fingerprint on an intermediate is a legitimate audit finding for Person C,
    not an error to raise.
    """
    if path is None:
        return False
    text = str(path).strip()
    if not text:
        return False
    # QGIS's in-memory providers. A GDAL /vsimem/ path names a real dataset,
    # but one that lives in this process's memory and is gone when it exits.
    return not text.startswith(("memory:", "/vsimem/", "TEMPORARY_OUTPUT"))


def sha256_file(path: str | pathlib.Path) -> tuple[str, int]:
    """Stream a file through SHA-256. Returns `(hex digest, bytes read)`.

    Chunked because this runs inside the user's processing run against
    datasets that may be gigabytes (RULES.md §5.1 — never make QGIS the
    problem). The size is returned from the same pass rather than stat'd
    separately, so the two can never disagree about what was hashed.
    """
    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise FingerprintError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest(), total


def _schema_sample_digest(
    *,
    file_size_bytes: int,
    feature_count: int | None,
    field_names: Sequence[str],
    band_count: int | None,
    width: int | None,
    height: int | None,
    pixel_size: Sequence[float] | None,
) -> str:
    """Hash the shape of a dataset instead of its bytes (§6.4 fallback).

    Both layer models are described, because both reach this path and they
    have almost nothing structurally in common: a vector is summarised by how
    many features it holds and what its columns are called, a raster by its
    grid — band count, dimensions, and ground size per pixel. The irrelevant
    half stays None, mirroring how CONTRACT_event.md shapes a layer entry.

    Describing only the vector half is not a smaller version of this; it is
    broken. Rasters are the files that actually exceed the threshold, and with
    the vector fields alone the digest collapses to a hash of the file size —
    which makes any two same-sized rasters identical.

    Sorted keys and an explicit separator so the digest depends on the values
    and not on dict ordering or json's default spacing — a fingerprint that
    changes when the serializer does is worthless for change detection.

    Field names keep their order: reordering columns is a schema change, and
    sorting them here would hide it. `pixel_size` is ordered for the same
    reason — [30.0, 10.0] is not the same grid as [10.0, 30.0].
    """
    payload = json.dumps(
        {
            # Bumped from /1, which described vectors only. A digest from the
            # older inputs is not comparable with one from these, so the
            # version travels inside the hash rather than beside it.
            "algorithm": "geoprovenance/schema_sample/2",
            "file_size_bytes": file_size_bytes,
            "feature_count": feature_count,
            "field_names": list(field_names),
            "band_count": band_count,
            "width": width,
            "height": height,
            "pixel_size": list(pixel_size) if pixel_size is not None else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_file(
    path: str | pathlib.Path,
    *,
    feature_count: int | None = None,
    field_names: Sequence[str] | None = None,
    band_count: int | None = None,
    width: int | None = None,
    height: int | None = None,
    pixel_size: Sequence[float] | None = None,
    threshold_bytes: int = LARGE_FILE_THRESHOLD_BYTES,
) -> Fingerprint:
    """Fingerprint one dataset, picking the §6.4 strategy by size.

    Everything after `path` is layer description, consulted only on the
    `schema_sample` path, and named to match a CONTRACT_event.md layer entry
    so a caller can pass one straight through. Vector layers carry
    `feature_count` / `field_names`; rasters carry `band_count` / `width` /
    `height` / `pixel_size`; the other half is None either way.

    It comes from the caller rather than being read here because that would
    need a format reader per driver — and the capture side already holds the
    open layer that knows. Only `field_names` has no home on the event yet.

    Raises `FingerprintError` if the file is unreadable, if `path` is not
    something that can be hashed (check `can_fingerprint` first), or if a file
    is over the threshold and no description was supplied to fall back on —
    silently hashing nothing would produce a confident wrong answer.
    """
    if not can_fingerprint(path):
        raise FingerprintError(
            f"{path!r} has no bytes on disk to hash — memory and temporary "
            f"layers reach Person B as path=None (CONTRACT_event.md rule 1). "
            f"Call can_fingerprint() first and record the skip instead."
        )

    target = pathlib.Path(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise FingerprintError(f"cannot stat {path}: {exc}") from exc

    if size <= threshold_bytes:
        digest, hashed_bytes = sha256_file(target)
        return Fingerprint(
            hash_value=digest,
            hash_strategy=STRATEGY_FILE,
            file_size_bytes=hashed_bytes,
            feature_count=feature_count,
        )

    # Size alone is not a fingerprint. Without at least one descriptive value
    # the digest reduces to a hash of the byte count, and any two same-sized
    # datasets — two 600 MB rasters, say — come out identical.
    described = (feature_count, field_names, band_count, width, height, pixel_size)
    if all(value is None or value == () or value == [] for value in described):
        raise FingerprintError(
            f"{path} is {size} bytes, over the {threshold_bytes}-byte threshold, "
            f"so the §6.4 fallback applies — but nothing was supplied to describe "
            f"it. Pass the layer's feature_count/field_names (vector) or "
            f"band_count/width/height/pixel_size (raster) from the capture event, "
            f"or raise threshold_bytes to hash the file in full."
        )

    return Fingerprint(
        hash_value=_schema_sample_digest(
            file_size_bytes=size,
            feature_count=feature_count,
            field_names=field_names or (),
            band_count=band_count,
            width=width,
            height=height,
            pixel_size=pixel_size,
        ),
        hash_strategy=STRATEGY_SCHEMA_SAMPLE,
        file_size_bytes=size,
        feature_count=feature_count,
    )
