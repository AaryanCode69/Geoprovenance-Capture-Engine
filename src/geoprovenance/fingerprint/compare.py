"""Deciding what changed about a file, not merely whether it changed.

Owner: Person B.  Research doc §9.1 RQ3 — detection accuracy.

    RULES.md §2.2 — standard library only.
    RULES.md §4.1 — imports no QGIS.
    RULES.md §5.6 — anything unresolvable becomes "unknown", never a guess.

Why this module has to exist
    Comparing two byte hashes yields one bit, and Person C's audit has to turn
    that bit into a reproducibility score. A bit is not enough to score with:
    "this file is not what it was" covers a GeoPackage that was merely rewritten
    by a newer SQLite, which is not a reproducibility problem at all, and it
    fails to cover a Shapefile whose .dbf was edited, which is a serious one.

    `hash.py` records several measurements of one file at one instant — a byte
    hash and up to three descriptions of the data's shape. Each on its own is
    still one bit. Read TOGETHER they separate the cases:

        bytes moved, everything else held        -> the file was re-saved
        attribute values moved, geometry held    -> same shapes, edited data
        feature count or extent moved            -> the geometry changed
        field list or CRS moved                  -> the schema changed

What it refuses to do
    A signal that is missing on either side is reported as unavailable and
    takes no part in the verdict. It is never treated as "held". A GeoTIFF has
    no readable description, so a GeoTIFF whose bytes moved comes back as
    `changed` — today's answer, stated as today's answer, rather than a
    confident `resaved` inferred from three signals that were never measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .hash import (
    COMPLEMENTARY_STRATEGIES,
    STRATEGY_ATTRIBUTES,
    STRATEGY_FILE,
    STRATEGY_GEOMETRY,
    STRATEGY_SCHEMA_SAMPLE,
    STRATEGY_STRUCTURE,
)

#: Nothing we could measure moved.
VERDICT_UNCHANGED = "unchanged"

#: The bytes moved and the values in the file did not. The file was rewritten;
#: the data in it was not. This is the false positive that a byte hash alone
#: reports as a change. Requires the attribute signal on both sides — see
#: `compare_fingerprint_sets`.
VERDICT_RESAVED = "resaved"

#: Attribute values moved while the geometry held — "same shapes, different
#: data". This is the false negative a byte hash of a Shapefile's .shp misses
#: entirely, because the values live in the .dbf beside it.
VERDICT_ATTRIBUTES_CHANGED = "attributes_changed"

#: Feature count or extent moved.
VERDICT_GEOMETRY_CHANGED = "geometry_changed"

#: The field list, field types or CRS moved.
VERDICT_SCHEMA_CHANGED = "schema_changed"

#: Something moved, and there was not enough measured to say what. The honest
#: degradation to a plain same/different answer.
VERDICT_CHANGED = "changed"

#: Nothing could be compared at all — no strategy appears on both sides.
VERDICT_UNKNOWN = "unknown"


_PLAIN_ENGLISH = {
    VERDICT_UNCHANGED: "This file is exactly as it was.",
    VERDICT_RESAVED: (
        "This file was saved again, but the data inside it is unchanged — "
        "the short code for the file moved while everything we can check "
        "about its contents stayed the same."
    ),
    VERDICT_ATTRIBUTES_CHANGED: (
        "The shapes in this file are unchanged, but the information attached "
        "to them was edited."
    ),
    VERDICT_GEOMETRY_CHANGED: (
        "The shapes in this file changed — there are a different number of "
        "them, or they cover a different area."
    ),
    VERDICT_SCHEMA_CHANGED: (
        "The columns in this file changed — one was added, removed, renamed "
        "or re-typed, or the map coordinates it uses are different."
    ),
    VERDICT_CHANGED: (
        "This file is different from what was recorded, and we cannot say in "
        "what way."
    ),
    VERDICT_UNKNOWN: (
        "We have nothing to compare — the two records were not measured the "
        "same way."
    ),
}


@dataclass(frozen=True)
class Comparison:
    """What two sets of fingerprints for one file say when read together."""

    verdict: str
    moved: frozenset[str]
    held: frozenset[str]
    unavailable: frozenset[str]

    @property
    def changed(self) -> bool:
        """Whether the DATA changed, which a re-save does not.

        `resaved` is deliberately False here. Reporting it as changed is the
        false positive this whole layer exists to remove, and Person C's
        "is this input unchanged?" component should score it as unchanged.
        `unknown` is also False, because an unmeasured file is not evidence of
        an edit; it is reported through `verdict`, which is what an audit
        should surface.
        """
        return self.verdict in (
            VERDICT_ATTRIBUTES_CHANGED,
            VERDICT_GEOMETRY_CHANGED,
            VERDICT_SCHEMA_CHANGED,
            VERDICT_CHANGED,
        )

    def explain(self) -> str:
        """One plain sentence, for Person C's report and the demo (RULES.md §7.5)."""
        sentence = _PLAIN_ENGLISH[self.verdict]
        if self.unavailable and self.verdict in (VERDICT_CHANGED, VERDICT_RESAVED):
            sentence += (
                " (Some checks could not be run on this kind of file, so this "
                "is the most we can say.)"
            )
        return sentence


def compare_fingerprint_sets(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> Comparison:
    """Compare two `hash_strategy -> hash_value` maps for one file.

    Both come from `ProvenanceStore.get_fingerprint_set()`, which returns every
    strategy recorded for one entity at its most recent instant.

    Only strategies present on BOTH sides take part. A strategy on one side
    only means the two measurements were taken by different versions of this
    code, or of a file whose format one of them could not read; either way it
    carries no information about whether the data changed, and counting it as
    agreement would manufacture a `resaved` verdict out of a missing signal.

    `schema_sample` is treated as a primary signal alongside `file` because it
    stands in for one: a dataset over the §6.4 threshold has one or the other,
    never both, and both answer "are these the same bytes, as best we can tell".
    """
    shared = set(before) & set(after)
    moved = frozenset(key for key in shared if before[key] != after[key])
    held = frozenset(shared - moved)
    unavailable = frozenset(COMPLEMENTARY_STRATEGIES - shared)

    def result(verdict: str) -> Comparison:
        return Comparison(
            verdict=verdict, moved=moved, held=held, unavailable=unavailable
        )

    if not shared:
        return result(VERDICT_UNKNOWN)

    # Ordered most-structural first. When a column was added AND features were
    # edited, "the columns changed" is the finding that explains the rest — a
    # schema change is why every downstream step may now behave differently,
    # and `moved` still carries the full set for a caller that wants it.
    if STRATEGY_STRUCTURE in moved:
        return result(VERDICT_SCHEMA_CHANGED)
    if STRATEGY_GEOMETRY in moved:
        return result(VERDICT_GEOMETRY_CHANGED)

    if STRATEGY_ATTRIBUTES in moved:
        # Only claim the shapes are untouched if the shapes were actually
        # checked. Without a geometry signal on both sides this is just "it
        # changed", which is true and is all that was measured.
        if STRATEGY_GEOMETRY in held:
            return result(VERDICT_ATTRIBUTES_CHANGED)
        return result(VERDICT_CHANGED)

    if not moved:
        return result(VERDICT_UNCHANGED)

    # Bytes moved and nothing about the data did — but "nothing about the data
    # changed" is a claim about the VALUES, so it takes the signal that looks at
    # values. `structure` and `geometry` held only say the columns and the
    # extent are as they were, and a row can be edited without disturbing
    # either; concluding `resaved` from those two would be the same
    # unmeasured-equals-unchanged mistake this module refuses everywhere else,
    # in the direction that hides a real edit.
    #
    # In practice this only bites on a GeoPackage past the attribute row
    # ceiling, which is exactly the case where we genuinely cannot tell a
    # rewrite from an edit. `changed` is the true answer there, and `explain()`
    # says that some checks could not be run.
    bytes_moved = moved & {STRATEGY_FILE, STRATEGY_SCHEMA_SAMPLE}
    if bytes_moved and STRATEGY_ATTRIBUTES in held:
        return result(VERDICT_RESAVED)
    return result(VERDICT_CHANGED)
