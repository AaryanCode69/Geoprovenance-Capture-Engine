"""SHA-256 dataset fingerprinting, with the §6.4 tiered fallback.

Owner: Person B.  Research doc §4.3 Layer 3, §6.4.

    RULES.md §2.2 — standard library only: `hashlib`, `json`, `pathlib`, plus
    this package's own `readers`, which is standard library too.
    RULES.md §1.3 — this module computes; it never writes. The caller hands the
    result to `ProvenanceStore.add_fingerprint()`.

Two PRIMARY strategies, chosen by file size (research doc §6.4). Exactly one
of these is produced for a dataset:

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

Three COMPLEMENTARY strategies, produced alongside the primary one whenever
`readers.describe()` can read the file. These are not weaker substitutes for
the byte hash; they answer a different question, and the answer only exists
when they are compared against it:

    structure       the field names, field types and CRS. Survives a re-save;
                    moves when a column is added, renamed, retyped or reordered.
    geometry        the feature count and bounding box. Survives a re-save;
                    moves when features are added, removed or relocated.
    attributes      the attribute values themselves — for a Shapefile the .dbf,
                    which the byte hash of the .shp never touches. Survives a
                    re-save; moves when one value in one row is edited.

Why the complementary strategies exist at all
    A byte hash gives a same/different answer, and it is wrong in both
    directions often enough to matter to RQ3 (research doc §9.1, detection
    accuracy = correctly detected changes / total changes).

    Wrong as a FALSE POSITIVE: a GeoPackage re-saved by a different SQLite
    build has different bytes and identical data — measured in this repository
    at bytes 92-99 and offset 7368 across builds, with rows and schema text
    unchanged. A byte hash that moved while structure, geometry and attributes
    all held is a re-save, and `compare.py` says so.

    Wrong as a FALSE NEGATIVE: a Shapefile is four files and the record points
    at the .shp, so editing a name in the .dbf changes nothing the byte hash
    reads. The `attributes` signal is the one that sees it.

    §6.4 lists "feature-count + schema hash" only as a fallback for files over
    the threshold, where it is strictly weaker than hashing the bytes. Run
    ALONGSIDE the byte hash instead of instead of it, the same measurement
    stops being a weaker answer and becomes a second axis.

The three are separate rows rather than one combined digest because a combined
digest would move whenever anything moved, which is the binary answer again.
`fingerprints UNIQUE(entity_id, hash_strategy, computed_at)` is what lets them
land together (docs/CONTRACT_schema.md, decision 4, v2).

Why the threshold is a parameter and not a constant read at call time: RQ3
measures change-detection accuracy, and an experiment that cannot vary the
threshold cannot show where the fallback starts costing accuracy.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from . import readers

#: Written into `fingerprints.hash_algorithm`. The column defaults to this too.
HASH_ALGORITHM = "SHA-256"

#: research doc §6.4 — "<1s for <500MB" is the measured basis for full hashing.
LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024

#: `fingerprints.hash_strategy` values. Person A's schema column, B's vocabulary.
#:
#: The column has no CHECK constraint, deliberately: constraining it would mean
#: a schema migration every time a strategy is added, and these constants are
#: the single place the vocabulary is defined. `KNOWN_STRATEGIES` is what the
#: tests assert against instead, so a typo still fails somewhere.
STRATEGY_FILE = "file"
STRATEGY_SCHEMA_SAMPLE = "schema_sample"
STRATEGY_STRUCTURE = "structure"
STRATEGY_GEOMETRY = "geometry"
STRATEGY_ATTRIBUTES = "attributes"

#: Exactly one of these is produced per dataset.
PRIMARY_STRATEGIES = frozenset({STRATEGY_FILE, STRATEGY_SCHEMA_SAMPLE})

#: Produced in addition, when the file can be read. Each may be absent, and an
#: absent signal compares as "unknown" rather than as "unchanged" (`compare.py`).
COMPLEMENTARY_STRATEGIES = frozenset(
    {STRATEGY_STRUCTURE, STRATEGY_GEOMETRY, STRATEGY_ATTRIBUTES}
)

KNOWN_STRATEGIES = PRIMARY_STRATEGIES | COMPLEMENTARY_STRATEGIES

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


# --------------------------------------------------------------------------
# Complementary signals
# --------------------------------------------------------------------------


def _json_digest(algorithm: str, payload: dict[str, Any]) -> str:
    """Digest a description, with the algorithm name travelling inside the hash.

    The name is part of the hashed payload rather than a column beside it for
    the reason `_schema_sample_digest` already gives: if what goes into a
    digest ever changes, every old value must stop comparing equal to every new
    one. A version that sat outside the hash could be ignored by a caller
    comparing two hex strings, and a changed recipe would then read as a
    changed file.

    Sorted keys and explicit separators so the digest depends on the values and
    not on dict ordering or json's default spacing.
    """
    body = dict(payload)
    body["algorithm"] = algorithm
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _stream_digest(algorithm: str, chunks: Iterable[bytes]) -> tuple[str, int]:
    """Digest a stream of bytes, prefixed by the algorithm name. Returns `(hex, bytes)`.

    Streamed rather than joined because the attribute table of a large
    Shapefile is a file in its own right, and this runs inside a user's
    processing run (RULES.md §5.1).
    """
    digest = hashlib.sha256()
    digest.update(algorithm.encode("utf-8") + b"\x00")
    total = 0
    for chunk in chunks:
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


#: Version tags for the three complementary digests. Bump one and every value
#: it ever produced stops comparing equal — which is correct, and is why the
#: tag is inside the payload.
STRUCTURE_ALGORITHM = "geoprovenance/structure/1"
GEOMETRY_ALGORITHM = "geoprovenance/geometry/1"
ATTRIBUTES_ALGORITHM = "geoprovenance/attributes/1"


def _total_feature_count(description: readers.DatasetDescription) -> int | None:
    counts = [
        layer.feature_count
        for layer in description.layers
        if layer.feature_count is not None
    ]
    return sum(counts) if counts else None


def complementary_fingerprints(
    path: str | pathlib.Path,
    *,
    description: readers.DatasetDescription | None = None,
    max_attribute_rows: int = readers.DEFAULT_MAX_ATTRIBUTE_ROWS,
) -> list[Fingerprint]:
    """The signals that make a byte hash interpretable. Never raises.

    Returns an empty list when the file is a format `readers` cannot read — a
    GeoTIFF, say. That is not a failure: an absent signal compares as `unknown`
    rather than as `unchanged`, so the audit degrades to today's same/different
    answer and says that it has, instead of inventing an axis it cannot measure.

    `file_size_bytes` is set only where a number of bytes was actually read.
    `structure` and `geometry` are digests of a description, not of a byte
    range, and recording a size against them would imply a coverage they do
    not have.
    """
    description = description if description is not None else readers.describe(path)
    if description is None:
        return []

    feature_count = _total_feature_count(description)
    results = [
        Fingerprint(
            hash_value=_json_digest(
                STRUCTURE_ALGORITHM, description.structure_payload()
            ),
            hash_strategy=STRATEGY_STRUCTURE,
            file_size_bytes=None,
            feature_count=feature_count,
        ),
        Fingerprint(
            hash_value=_json_digest(
                GEOMETRY_ALGORITHM, description.geometry_payload()
            ),
            hash_strategy=STRATEGY_GEOMETRY,
            file_size_bytes=None,
            feature_count=feature_count,
        ),
    ]

    chunks = readers.attribute_chunks(path, max_rows=max_attribute_rows)
    if chunks is not None:
        digest, read_bytes = _stream_digest(ATTRIBUTES_ALGORITHM, chunks)
        results.append(
            Fingerprint(
                hash_value=digest,
                hash_strategy=STRATEGY_ATTRIBUTES,
                file_size_bytes=read_bytes,
                feature_count=feature_count,
            )
        )
    return results


def fingerprint_dataset(
    path: str | pathlib.Path,
    *,
    feature_count: int | None = None,
    field_names: Sequence[str] | None = None,
    band_count: int | None = None,
    width: int | None = None,
    height: int | None = None,
    pixel_size: Sequence[float] | None = None,
    threshold_bytes: int = LARGE_FILE_THRESHOLD_BYTES,
    max_attribute_rows: int = readers.DEFAULT_MAX_ATTRIBUTE_ROWS,
) -> list[Fingerprint]:
    """Every fingerprint for one dataset: the primary one, plus what can be read.

    This is what a caller should use. `fingerprint_file` remains exactly as it
    was — one strategy, one result — because it is Person B's published entry
    point and RULES.md §1.5 makes its signature an interface; this is a second
    door, not a change to that one.

    The result is ordered primary-first and every `hash_strategy` in it is
    distinct, so the whole list can be written in one transaction under
    `fingerprints UNIQUE(entity_id, hash_strategy, computed_at)` — which is the
    constraint the v2 schema change widened to permit exactly this.

    Values read off disk fill in for values the caller did not supply. That
    closes a gap `fingerprint_file` still carries in its docstring: the capture
    event has nowhere to put `field_names`, so before this the §6.4 fallback
    could only ever see a feature count. A dataset over the threshold whose
    file can be read now gets a real schema digest instead of refusing.

    Raises `FingerprintError` only where `fingerprint_file` would: an
    unhashable path, an unreadable file, or a file over the threshold that
    nothing — neither the caller nor the reader — can describe.
    """
    description = readers.describe(path)

    if description is not None:
        first = description.layers[0] if description.layers else None
        if feature_count is None:
            feature_count = _total_feature_count(description)
        if field_names is None and first is not None:
            field_names = first.field_names

    primary = fingerprint_file(
        path,
        feature_count=feature_count,
        field_names=field_names,
        band_count=band_count,
        width=width,
        height=height,
        pixel_size=pixel_size,
        threshold_bytes=threshold_bytes,
    )
    return [primary] + complementary_fingerprints(
        path, description=description, max_attribute_rows=max_attribute_rows
    )
