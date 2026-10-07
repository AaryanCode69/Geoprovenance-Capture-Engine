"""Coastal case-study perturbation analysis — run outside QGIS.

Environment note: this run has no GDAL/QGIS available (no `osgeo`, no
`ogr2ogr`), so it differs from `perturbations.py` in two ways, both
documented in the manuscript rather than hidden:
  - P1 and P4 are run on the GeoPackage boundary-line file (the format the
    coastal pipeline actually produces throughout), not converted to
    Shapefile first. The Shapefile .dbf blind spot is separately
    demonstrated in the repo's own S4.1 fixtures (already verified, see
    "Current context of Project.pdf" Part 4.1), so this is not a gap in
    coverage, just a difference in which run demonstrates which format.
  - Everything here uses only `geoprovenance.fingerprint` (pure stdlib,
    confirmed no qgis/osgeo import) plus raw `sqlite3` reads of the
    already-computed GeoPackage attribute tables from the real QGIS runs
    done in an earlier session (data/derived/epr_classified.gpkg,
    data/perturbations/p2/epr_perturbed.gpkg). No geometry is parsed or
    recomputed - only attribute columns already written by that QGIS run.

Writes experiments/coastal-shoreline/perturbation_results.json - the raw
numbers behind every figure quoted in the manuscript sections.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import statistics
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "experiments" / "coastal-shoreline"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(EXP))

from geoprovenance.fingerprint.hash import fingerprint_dataset          # noqa: E402
from geoprovenance.fingerprint.compare import compare_fingerprint_sets  # noqa: E402
import scenario                                                          # noqa: E402

RESULTS: dict = {"perturbations": [], "baseline_summary": {}, "capture_summary": {}}


def fp(path: pathlib.Path) -> dict[str, str]:
    return {f.hash_strategy: f.hash_value for f in fingerprint_dataset(path)}


def record(name, expected, cmp, extra=None):
    row = {
        "perturbation": name,
        "expected_verdict": expected,
        "actual_verdict": cmp.verdict,
        "matches_expected": cmp.verdict == expected,
        "moved": sorted(cmp.moved),
        "held": sorted(cmp.held),
        "explanation": cmp.explain(),
    }
    if extra:
        row.update(extra)
    RESULTS["perturbations"].append(row)
    mark = "OK " if row["matches_expected"] else "MISMATCH"
    print(f"  [{mark}] {name}: expected={expected!r} actual={cmp.verdict!r}  ({cmp.explain()})")


print("\n=== P1 - silent re-save (GeoPackage, different GDAL write path) ===")
p1_dir = EXP / "data" / "perturbations" / "p1"
for i in range(1, 4):
    orig, resaved = p1_dir / f"trial{i}_original.gpkg", p1_dir / f"trial{i}_resaved.gpkg"
    if not (orig.exists() and resaved.exists()):
        print(f"  trial {i}: missing files, skipped")
        continue
    cmp = compare_fingerprint_sets(fp(orig), fp(resaved))
    record(f"P1 trial {i}", "resaved", cmp, extra={"delta_epr_m_per_yr": 0.0, "note": "bytes copied verbatim by ogr2ogr; rate not re-derived, so delta is 0 by construction"})

print("\n=== P4 - attribute edit (GeoPackage, .dbf-equivalent value changed) ===")
p4_dir = EXP / "data" / "perturbations" / "p4"
src = scenario.SCENES[1]["boundary_lines"]
for i in range(1, 4):
    trial_dir = p4_dir / f"trial{i}"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True)
    gpkg_path = trial_dir / "shoreline.gpkg"
    shutil.copy(src, gpkg_path)

    before = fp(gpkg_path)
    conn = sqlite3.connect(gpkg_path)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM gpkg_contents LIMIT 1")
    table = cur.fetchone()[0]
    cur.execute(f'PRAGMA table_info("{table}")')
    cols = [r[1] for r in cur.fetchall()]
    edit_col = "is_water" if "is_water" in cols else next(c for c in cols if c not in ("fid", "geom"))
    cur.execute(f'SELECT fid, "{edit_col}" FROM "{table}" LIMIT 1')
    fid, old_val = cur.fetchone()
    new_val = (old_val + 1) if isinstance(old_val, (int, float)) else old_val
    # This environment's sqlite3 has no ST_IsEmpty/ST_MinX/etc (no SpatiaLite
    # extension loaded), and the GeoPackage's rtree-maintenance triggers on
    # this table reference those functions even in an unreached WHEN branch
    # (SQLite resolves function names at prepare time, not just when a branch
    # actually runs). We only ever touch a non-geometry column here, so the
    # rtree index is never actually out of date; we drop those triggers,
    # make the UPDATE, then restore them byte-for-byte from sqlite_master.
    cur.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name = ? AND sql LIKE '%ST_%'",
        (table,),
    )
    spatialite_triggers = cur.fetchall()
    for name, _sql in spatialite_triggers:
        cur.execute(f'DROP TRIGGER "{name}"')
    cur.execute(f'UPDATE "{table}" SET "{edit_col}" = ? WHERE fid = ?', (new_val, fid))
    for _name, sql in spatialite_triggers:
        cur.execute(sql)
    conn.commit()
    conn.close()
    after = fp(gpkg_path)

    cmp = compare_fingerprint_sets(before, after)
    record(
        f"P4 trial {i}", "attributes_changed", cmp,
        extra={
            "edited_column": edit_col, "edited_fid": fid,
            "old_value": old_val, "new_value": new_val,
            "geoscience_effect": "none - the distance/EPR steps join shorelines by nearest geometry only; this attribute is never read downstream",
        },
    )

print("\n=== P5 - control (no change) ===")
for i in range(1, 4):
    before = fp(src)
    after = fp(src)
    cmp = compare_fingerprint_sets(before, after)
    record(f"P5 trial {i}", "unchanged", cmp, extra={"delta_epr_m_per_yr": 0.0})

print("\n=== P2 - re-thresholded index (t=0.0 -> t=0.02), detection ===")
p2_dir = EXP / "data" / "perturbations" / "p2"
baseline_boundary = scenario.SCENES[1]["boundary_lines"]
perturbed_boundary = p2_dir / f"{scenario.SCENES[1]['date']}_boundary_lines.gpkg"
cmp = compare_fingerprint_sets(fp(baseline_boundary), fp(perturbed_boundary))
record("P2 (detection)", "geometry_changed", cmp)

print("\n=== P2 - geoscience effect (from the real QGIS-computed attribute tables) ===")


def read_gpkg_table(path, table, cols):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(f'SELECT {", ".join(cols)} FROM "{table}"')
    rows = cur.fetchall()
    conn.close()
    return rows


baseline_rows = read_gpkg_table(
    EXP / "data" / "derived" / "epr_classified.gpkg", "epr_classified",
    ["d2015_fid", "epr_m_per_yr", "classification"],
)
original_by_fid = {fid: (epr, cls) for fid, epr, cls in baseline_rows if fid is not None}

perturbed_rows = read_gpkg_table(
    p2_dir / "epr_perturbed.gpkg", "epr_perturbed",
    ["d2015_fid", "dist_2015_m", "dist_2026_m", "epr_m_per_yr"],
)

deltas, reclassified, matched = [], 0, 0
PLAUSIBLE_DISTANCE_M = scenario.PLAUSIBLE_DISTANCE_M
for fid, d2015, d2026p, epr_p in perturbed_rows:
    orig = original_by_fid.get(fid)
    if orig is None or d2015 is None or d2026p is None or epr_p is None:
        continue
    if d2015 >= PLAUSIBLE_DISTANCE_M or d2026p >= PLAUSIBLE_DISTANCE_M:
        continue
    matched += 1
    orig_epr, orig_class = orig
    deltas.append(epr_p - orig_epr)
    pert_class = "unknown"
    for lo, hi, label in scenario.EPR_BANDS:
        if lo <= epr_p < hi:
            pert_class = label
            break
    if pert_class != orig_class:
        reclassified += 1

p2_geoscience = {
    "matched_plausible_transects": matched,
    "mean_delta_epr_m_per_yr": statistics.mean(deltas) if deltas else None,
    "median_delta_epr_m_per_yr": statistics.median(deltas) if deltas else None,
    "max_abs_delta_epr_m_per_yr": max(abs(d) for d in deltas) if deltas else None,
    "stdev_delta_epr_m_per_yr": statistics.pstdev(deltas) if len(deltas) > 1 else None,
    "reclassified_count": reclassified,
    "reclassified_pct": (100 * reclassified / matched) if matched else None,
}
RESULTS["perturbations"].append({"perturbation": "P2 (geoscience effect)", **p2_geoscience})
print(f"  matched, plausible transects: {matched}")
if deltas:
    print(f"  mean delta EPR   : {p2_geoscience['mean_delta_epr_m_per_yr']:+.4f} m/yr")
    print(f"  median delta EPR : {p2_geoscience['median_delta_epr_m_per_yr']:+.4f} m/yr")
    print(f"  max |delta EPR|  : {p2_geoscience['max_abs_delta_epr_m_per_yr']:.4f} m/yr")
if matched:
    print(f"  reclassified: {reclassified}/{matched} ({p2_geoscience['reclassified_pct']:.1f}%)")
else:
    print("  reclassified: n/a")

print("\n=== Baseline EPR summary (2015-06-24 -> 2026-08-01, 11.06 yr) ===")
baseline_full = read_gpkg_table(
    EXP / "data" / "derived" / "epr_classified.gpkg", "epr_classified",
    ["dist_2015_m", "dist_2026_m", "epr_m_per_yr", "classification"],
)
plausible = [r for r in baseline_full if r[0] is not None and r[1] is not None and r[0] < PLAUSIBLE_DISTANCE_M and r[1] < PLAUSIBLE_DISTANCE_M]
eprs = [r[2] for r in plausible if r[2] is not None]
class_counts: dict[str, int] = {}
for r in plausible:
    class_counts[r[3]] = class_counts.get(r[3], 0) + 1

baseline_summary = {
    "total_rows_in_gpkg": len(baseline_full),
    "plausible_transect_points": len(plausible),
    "mean_epr_m_per_yr": statistics.mean(eprs) if eprs else None,
    "median_epr_m_per_yr": statistics.median(eprs) if eprs else None,
    "stdev_epr_m_per_yr": statistics.pstdev(eprs) if len(eprs) > 1 else None,
    "min_epr_m_per_yr": min(eprs) if eprs else None,
    "max_epr_m_per_yr": max(eprs) if eprs else None,
    "classification_counts": class_counts,
    "classification_pct": {k: round(100 * v / len(plausible), 1) for k, v in class_counts.items()} if plausible else {},
}
RESULTS["baseline_summary"] = baseline_summary
print(json.dumps(baseline_summary, indent=2, default=str))

conn = sqlite3.connect(f"file:{EXP / 'data' / 'provenance.db'}?mode=ro", uri=True)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM activities")
n_activities = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM entities")
n_entities = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM relations")
n_relations = cur.fetchone()[0]
cur.execute("SELECT algorithm_id, count(*) FROM activities GROUP BY algorithm_id ORDER BY algorithm_id")
by_alg = cur.fetchall()
conn.close()
capture_summary = {
    "jobs_recorded": n_activities, "files_known": n_entities, "relations": n_relations,
    "by_algorithm": {a: c for a, c in by_alg},
    "channel": "processing.run wrapper only (script-driven pipeline)",
    "qgis_version": "4.2.2",
}
RESULTS["capture_summary"] = capture_summary
print("\n=== Capture summary (real QGIS run, processing.run channel) ===")
print(json.dumps(capture_summary, indent=2))

out_json = EXP / "perturbation_results.json"
out_json.write_text(json.dumps(RESULTS, indent=2, default=str))
print(f"\nWrote {out_json}")
