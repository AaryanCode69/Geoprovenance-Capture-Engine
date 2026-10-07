"""The protocol's §5 perturbation matrix (P1, P2, P4, P5 — P3 needs a third,
different-vintage scene that hasn't been downloaded).

    PYTHONPATH=/usr/share/qgis/python/plugins:<repo root> \\
      QT_QPA_PLATFORM=offscreen python3 experiments/coastal-shoreline/perturbations.py

P1 (silent re-save), P4 (attribute edit) and P5 (control) touch no QGIS —
they only call `fingerprint_dataset`/`compare_fingerprint_sets`, which import
neither. P2 (re-thresholded index) needs a real re-run of the affected part
of the workflow through Processing, so GeoProvenance captures it, per the
protocol's "any custom rate math runs through Processing too".

Each perturbation is introduced on a COPY, never on the baseline's own
output files — the protocol's "in isolation, reset to the clean state
between them" (§5).
"""

from __future__ import annotations

import pathlib
import shutil
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import scenario                                                        # noqa: E402
from geoprovenance.fingerprint.compare import compare_fingerprint_sets  # noqa: E402
from geoprovenance.fingerprint.hash import fingerprint_dataset          # noqa: E402

PERT_DIR = scenario.EXPERIMENT_ROOT / "data" / "perturbations"
RESULTS: list[dict] = []


def fp_dict(path) -> dict[str, str]:
    return {f.hash_strategy: f.hash_value for f in fingerprint_dataset(path)}


def record(name: str, expected_verdict: str, cmp, extra: dict | None = None) -> None:
    row = {
        "perturbation": name,
        "expected_verdict": expected_verdict,
        "actual_verdict": cmp.verdict,
        "matches_expected": cmp.verdict == expected_verdict,
        "changed_flag": cmp.changed,
        "moved": sorted(cmp.moved),
        "held": sorted(cmp.held),
        "explanation": cmp.explain(),
    }
    if extra:
        row.update(extra)
    RESULTS.append(row)
    status = "OK " if row["matches_expected"] else "MISMATCH"
    print(f"  [{status}] {name}: expected={expected_verdict!r} actual={cmp.verdict!r}")
    print(f"           {cmp.explain()}")


# ---------------------------------------------------------------------------
# P1 — silent re-save (no QGIS needed)
# ---------------------------------------------------------------------------

def run_p1() -> None:
    print("\nP1 — silent re-save (different GDAL write path, same data)")
    src = scenario.SCENES[1]["boundary_lines"]  # 2026 shoreline
    out_dir = PERT_DIR / "p1"
    out_dir.mkdir(parents=True, exist_ok=True)
    for trial in range(1, 4):
        original = out_dir / f"trial{trial}_original.gpkg"
        resaved = out_dir / f"trial{trial}_resaved.gpkg"
        shutil.copy(src, original)
        import subprocess
        subprocess.run(
            ["ogr2ogr", "-f", "GPKG", str(resaved), str(original)],
            check=True, capture_output=True,
        )
        before, after = fp_dict(original), fp_dict(resaved)
        cmp = compare_fingerprint_sets(before, after)
        record(f"P1 trial {trial}", "resaved", cmp)


# ---------------------------------------------------------------------------
# P4 — attribute edit, geometry bytes untouched (no QGIS needed)
# ---------------------------------------------------------------------------

def run_p4() -> None:
    print("\nP4 — attribute edit (.dbf value changed, .shp bytes untouched)")
    from osgeo import ogr
    ogr.UseExceptions()

    src = scenario.SCENES[1]["boundary_lines"]  # 2026 shoreline
    out_dir = PERT_DIR / "p4"
    out_dir.mkdir(parents=True, exist_ok=True)
    for trial in range(1, 4):
        trial_dir = out_dir / f"trial{trial}"
        if trial_dir.exists():
            shutil.rmtree(trial_dir)
        trial_dir.mkdir(parents=True)
        shp_path = trial_dir / "shoreline.shp"

        import subprocess
        subprocess.run(
            ["ogr2ogr", "-f", "ESRI Shapefile", str(shp_path), str(src)],
            check=True, capture_output=True,
        )

        shp_bytes_before = shp_path.read_bytes()
        before = fp_dict(shp_path)

        ds = ogr.Open(str(shp_path), update=1)
        lyr = ds.GetLayer(0)
        feat = lyr.GetNextFeature()
        feat.SetField("is_water", 2)  # edit an EXISTING field's value, no new column
        lyr.SetFeature(feat)
        ds = None

        shp_bytes_after = shp_path.read_bytes()
        after = fp_dict(shp_path)

        cmp = compare_fingerprint_sets(before, after)
        record(
            f"P4 trial {trial}", "attributes_changed", cmp,
            extra={"shp_bytes_unchanged": shp_bytes_before == shp_bytes_after},
        )


# ---------------------------------------------------------------------------
# P5 — control, no change (no QGIS needed)
# ---------------------------------------------------------------------------

def run_p5() -> None:
    print("\nP5 — control (no change)")
    src = scenario.SCENES[1]["boundary_lines"]
    for trial in range(1, 4):
        before = fp_dict(src)
        after = fp_dict(src)
        cmp = compare_fingerprint_sets(before, after)
        record(f"P5 trial {trial}", "unchanged", cmp)


# ---------------------------------------------------------------------------
# P2 — re-thresholded index (needs QGIS; runs the affected steps for real)
# ---------------------------------------------------------------------------

#: The protocol's own example is 0.0 -> 0.1, but this scene's actual MNDWI
#: distribution doesn't support that jump: only 0.29% of all pixels (land
#: and sea) exceed 0.1 at all, so t=0.1 doesn't gently shift the coastline —
#: it fragments the sea itself into ~100 disconnected patches (largest 0.19
#: km^2, versus the true sea's 205.7 km^2), breaking the "largest connected
#: water body is the sea" step the whole pipeline depends on. That's a real,
#: reportable finding about threshold sensitivity, but it isn't what P2 is
#: meant to test (a change that "looks identical to an analyst"). 0.02 keeps
#: the sea the dominant polygon while still moving real pixels across the
#: line.
P2_THRESHOLD = 0.02

P2_DIR = PERT_DIR / "p2"


def _p2_scene() -> dict:
    scene = dict(scenario.SCENES[1])  # copy of the 2026 scene's dict
    scene["water_mask"] = P2_DIR / "water_mask.tif"
    scene["water_polygons"] = P2_DIR / "water_polygons.gpkg"
    scene["water_polygons_fixed"] = P2_DIR / "water_polygons_fixed.gpkg"
    scene["water_only"] = P2_DIR / "water_only.gpkg"
    scene["sea_polygon"] = P2_DIR / "sea_polygon.gpkg"
    # SAME filename stem as the original — GDAL defaults a GeoPackage's
    # internal layer name to the file stem, and `structure_payload` includes
    # that name. A different stem here would make `compare_fingerprint_sets`
    # see a "structure changed" that is really just this script naming its
    # own output differently, not anything the perturbation did.
    scene["boundary_lines"] = P2_DIR / f"{scene['date']}_boundary_lines.gpkg"
    return scene


def run_p2_qgis() -> None:
    """Re-derive the 2026 shoreline at a different MNDWI cutoff, then redo
    just the "distance to 2026" half of the rate calculation — holding the
    baseline and the 2015 measurements fixed, so the only thing that can
    move is what P2 actually touched.

    Routed through `processing.run` with GeoProvenance's real capture engine
    installed, not called directly — the protocol's "any custom rate math
    runs through Processing too, so it is captured" means captured for real,
    not merely eligible to be.
    """
    from qgis.core import QgsApplication

    import processing
    from processing.core.Processing import Processing
    Processing.initialize()

    from geoprovenance.capture import hooks
    from geoprovenance.capture.engine import ProvenanceCaptureEngine
    from geoprovenance.storage.store import ProvenanceStore

    P2_DIR.mkdir(parents=True, exist_ok=True)
    perturbed = _p2_scene()

    print(f"\nP2 — re-thresholded index (t=0.0 -> t={P2_THRESHOLD}), re-derive, "
          f"recompute the rate")

    db_path = P2_DIR / "provenance.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = db_path.with_name(db_path.name + suffix)
        if candidate.exists():
            candidate.unlink()

    store = ProvenanceStore(db_path)
    engine = ProvenanceCaptureEngine.start(store)
    hook_dir = P2_DIR / "_hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)

    undo = []
    original_threshold = scenario.MNDWI_THRESHOLD
    try:
        for _description, undo_fn in hooks.install_all(engine, hook_dir):
            undo.append(undo_fn)

        scenario.MNDWI_THRESHOLD = P2_THRESHOLD
        try:
            for step in [
                scenario._threshold_step(perturbed),
                scenario._polygonize_step(perturbed),
                scenario._fix_geometries_step(perturbed),
                scenario._keep_water_step(perturbed),
                scenario._keep_sea_step(perturbed),
                scenario._boundary_step(perturbed),
            ]:
                print(f"  running: {step['algorithm_id']}")
                processing.run(step["algorithm_id"], dict(step["parameters"]))
        finally:
            scenario.MNDWI_THRESHOLD = original_threshold

        # Detection: does fingerprinting/compare correctly call this a
        # geometry change, not a re-save and not "changed" with no
        # explanation?
        before = fp_dict(scenario.SCENES[1]["boundary_lines"])  # the ORIGINAL t=0.0 result
        after = fp_dict(perturbed["boundary_lines"])
        cmp = compare_fingerprint_sets(before, after)
        record("P2 (detection)", "geometry_changed", cmp)

        # Geoscience effect: redo the "distance to 2026" half only. The
        # baseline points and the "distance to 2015" measurements are
        # UNCHANGED by this perturbation, so they are reused rather than
        # recomputed.
        perturbed_dist_2026 = P2_DIR / "dist_to_perturbed_2026.gpkg"
        join_step = scenario._join_nearest_step(
            scenario.DIST_TO_2015, perturbed["boundary_lines"],
            "d2026p_", perturbed_dist_2026,
        )
        print(f"  running: {join_step['algorithm_id']} (against the perturbed shoreline)")
        processing.run(join_step["algorithm_id"], dict(join_step["parameters"]))

        dist_2026_field = P2_DIR / "dist_2026_field.gpkg"
        field_step = scenario._add_distance_field_step(
            perturbed_dist_2026, dist_2026_field, "dist_2026_m",
            "feature_x_2", "feature_y_2", "nearest_x_2", "nearest_y_2",
            "Work out how far the PERTURBED 2026 coastline is from each baseline point.",
        )
        print(f"  running: {field_step['algorithm_id']}")
        processing.run(field_step["algorithm_id"], dict(field_step["parameters"]))

        # dist_2026_field still carries the FIRST join's un-suffixed
        # feature_x/y + nearest_x/y (the 2015 measurement) untouched — turn
        # those into "dist_2015_m" too, the same way the baseline result did.
        dist_both_field = P2_DIR / "dist_both_field.gpkg"
        field_step_2015 = scenario._add_distance_field_step(
            dist_2026_field, dist_both_field, "dist_2015_m",
            "feature_x", "feature_y", "nearest_x", "nearest_y",
            "Work out how far the 2015 coastline is from each baseline point "
            "(unchanged by this perturbation, recomputed for a matching schema).",
        )
        print(f"  running: {field_step_2015['algorithm_id']}")
        processing.run(field_step_2015["algorithm_id"], dict(field_step_2015["parameters"]))

        epr_step = {
            "algorithm_id": "native:fieldcalculator",
            "parameters": {
                "INPUT": str(dist_both_field),
                "FIELD_NAME": "epr_m_per_yr",
                "FIELD_TYPE": 0,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 4,
                "FORMULA": f'("dist_2015_m" - "dist_2026_m") / {scenario.SEPARATION_YEARS}',
                "OUTPUT": str(P2_DIR / "epr_perturbed.gpkg"),
            },
        }
        print(f"  running: {epr_step['algorithm_id']} (perturbed EPR)")
        processing.run(epr_step["algorithm_id"], dict(epr_step["parameters"]))
    finally:
        for undo_fn in reversed(undo):
            try:
                undo_fn()
            except Exception as exc:  # pragma: no cover - reported
                print(f"  teardown failed: {exc!r}")
        counts = store.counts()
        print(f"\n  GeoProvenance capture of this perturbation run: "
              f"{counts['activities']} jobs, {counts['entities']} files, "
              f"{counts['relations']} relations")
        ProvenanceCaptureEngine.stop()
        store.close()

    _compare_epr(P2_DIR / "epr_perturbed.gpkg")


def _compare_epr(perturbed_epr_path) -> None:
    """ΔEPR and % reclassified, matched by baseline point fid against the
    already-computed, already-filtered original result.
    """
    from osgeo import ogr
    ogr.UseExceptions()

    original_ds = ogr.Open(str(scenario.OUT_DIR / "epr_classified.gpkg"))
    original_lyr = original_ds.GetLayer(0)
    original_by_fid: dict[int, tuple[float, str]] = {}
    for f in original_lyr:
        fid = f.GetField("d2015_fid")
        original_by_fid[fid] = (f.GetField("epr_m_per_yr"), f.GetField("classification"))

    perturbed_ds = ogr.Open(str(perturbed_epr_path))
    perturbed_lyr = perturbed_ds.GetLayer(0)

    deltas = []
    reclassified = 0
    matched = 0
    for f in perturbed_lyr:
        fid = f.GetField("d2015_fid")
        original = original_by_fid.get(fid)
        if original is None:
            continue
        dist_2015 = f.GetField("dist_2015_m")
        dist_2026_p = f.GetField("dist_2026_m")
        if dist_2015 is None or dist_2026_p is None:
            continue
        if dist_2015 >= scenario.PLAUSIBLE_DISTANCE_M or dist_2026_p >= scenario.PLAUSIBLE_DISTANCE_M:
            continue  # same plausibility filter as the baseline result
        matched += 1
        perturbed_epr = f.GetField("epr_m_per_yr")
        original_epr, original_class = original
        deltas.append(perturbed_epr - original_epr)

        perturbed_class = "unknown"
        for lo, hi, label in scenario.EPR_BANDS:
            if lo <= perturbed_epr < hi:
                perturbed_class = label
                break
        if perturbed_class != original_class:
            reclassified += 1

    import statistics
    print()
    print(f"  P2 geoscience effect — {matched} matched, plausible transect points:")
    if deltas:
        print(f"    mean delta EPR   : {statistics.mean(deltas):+.4f} m/yr")
        print(f"    median delta EPR : {statistics.median(deltas):+.4f} m/yr")
        print(f"    max |delta EPR|  : {max(abs(d) for d in deltas):.4f} m/yr")
    print(f"    reclassified     : {reclassified} / {matched} "
          f"({100 * reclassified / matched:.1f}%)" if matched else "    reclassified: n/a")

    RESULTS.append({
        "perturbation": "P2 (geoscience effect)",
        "matched_points": matched,
        "mean_delta_epr": statistics.mean(deltas) if deltas else None,
        "median_delta_epr": statistics.median(deltas) if deltas else None,
        "pct_reclassified": 100 * reclassified / matched if matched else None,
    })


def main() -> int:
    import os
    from qgis.core import QgsApplication

    run_p1()
    run_p4()
    run_p5()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        run_p2_qgis()
    finally:
        app.exitQgis()

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    for row in RESULTS:
        if "matches_expected" in row:
            mark = "OK " if row["matches_expected"] else "!! "
            print(f"  {mark}{row['perturbation']:<20} "
                  f"expected={row['expected_verdict']:<20} got={row['actual_verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
