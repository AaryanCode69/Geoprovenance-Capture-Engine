"""The Cuddalore shoreline-change pipeline, defined once and driven by
``run_in_qgis.py`` — mirrors the pattern in ``qgis_demo/scenario.py``: one
definition of the workflow, run for real inside QGIS so GeoProvenance
captures every step through ``processing.run``.

Protocol: ``coastal-reproducibility-experiment-protocol.md`` §4 (baseline
workflow) and §5 (perturbation matrix). This file currently builds the
baseline only, phase by phase — see ``run_in_qgis.py`` for which phases are
wired up so far.

Scenes
    Two Landsat Collection 2 Level-2 scenes, same path/row (142/052), ~11
    years apart. Bookkeeping in ``scene_manifest.json``.

CRS
    The scenes' own projection, WGS 84 / UTM zone 44N (EPSG:32644) — metres,
    not degrees, so buffer/transect distances in the protocol's spec (metres)
    need no conversion. The AOI extent below is expressed in that CRS.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = REPO_ROOT / "experiments" / "coastal-shoreline"
RAW_ROOT = REPO_ROOT / "dataset-cuddalore-coast"
OUT_DIR = EXPERIMENT_ROOT / "data" / "derived"
DB_PATH = EXPERIMENT_ROOT / "data" / "provenance.db"

CRS = "EPSG:32644"

#: Cuddalore AOI, converted from 11°36'-11°51'N / 79°42'-79°51'E to metres in
#: EPSG:32644. Order matches QGIS's "xmin,xmax,ymin,ymax [crs]" extent string.
AOI_EXTENT = f"358266.7,374735.5,1282576.1,1310297.0 [{CRS}]"

#: MNDWI threshold. t = 0.0 is the protocol's default; the P2 perturbation
#: varies this later.
MNDWI_THRESHOLD = 0.0

# ---------------------------------------------------------------------------
# The two dated scenes
# ---------------------------------------------------------------------------

SCENES = [
    {
        "role": "baseline",
        "date": "2015-06-24",
        "scene_id": "LC08_L2SP_142052_20150624_20200909_02_T1",
    },
    {
        "role": "recent",
        "date": "2026-08-01",
        "scene_id": "LC09_L2SP_142052_20260801_20260802_02_T1",
    },
]


def _band_path(scene_id: str, band: str) -> pathlib.Path:
    return RAW_ROOT / scene_id / f"{scene_id}_{band}.TIF"


for _scene in SCENES:
    _scene["green"] = _band_path(_scene["scene_id"], "SR_B3")
    _scene["swir1"] = _band_path(_scene["scene_id"], "SR_B6")
    _scene["green_clip"] = OUT_DIR / f"{_scene['date']}_green_clip.tif"
    _scene["swir1_clip"] = OUT_DIR / f"{_scene['date']}_swir1_clip.tif"
    _scene["mndwi"] = OUT_DIR / f"{_scene['date']}_mndwi.tif"
    _scene["water_mask"] = OUT_DIR / f"{_scene['date']}_water_mask.tif"
    _scene["water_polygons"] = OUT_DIR / f"{_scene['date']}_water_polygons.gpkg"
    _scene["water_polygons_fixed"] = OUT_DIR / f"{_scene['date']}_water_polygons_fixed.gpkg"
    _scene["water_only"] = OUT_DIR / f"{_scene['date']}_water_only.gpkg"
    _scene["sea_polygon"] = OUT_DIR / f"{_scene['date']}_sea_polygon.gpkg"
    _scene["boundary_lines"] = OUT_DIR / f"{_scene['date']}_boundary_lines.gpkg"

INPUT_PATHS = tuple(
    p for scene in SCENES for p in (scene["green"], scene["swir1"])
)

# ---------------------------------------------------------------------------
# Baseline + transects (protocol §4 steps 5-8) — built once, from both dates
# ---------------------------------------------------------------------------

BASELINE_OFFSHORE_M = 80
TRANSECT_SPACING_M = 100
#: Long enough to cross both the sea and the AOI's landward extent from any
#: point on the offshore baseline ring.
TRANSECT_LENGTH_M = 3000

SHORELINES_MERGED = OUT_DIR / "shorelines_merged.gpkg"
BASELINE_BUFFER = OUT_DIR / "baseline_buffer.gpkg"
BASELINE_RING = OUT_DIR / "baseline_ring.gpkg"
BASELINE_DENSIFIED = OUT_DIR / "baseline_densified.gpkg"
BASELINE_POINTS = OUT_DIR / "baseline_points.gpkg"
TRANSECTS_RAW = OUT_DIR / "transects_raw.gpkg"

#: Years between the two scenes, for the rate calculation.
SEPARATION_YEARS = 11.06

DIST_TO_2015 = OUT_DIR / "dist_to_2015.gpkg"
DIST_TO_BOTH = OUT_DIR / "dist_to_both.gpkg"
EPR_RESULT = OUT_DIR / "epr_by_point.gpkg"

#: A baseline point only measures a real transect if its nearest match on
#: BOTH dated shorelines is close to the intended 80 m offshore offset. The
#: baseline ring also carries the buffer's landward arc and end-caps (the
#: two dated shorelines' 80 m buffers don't touch, so `native:polygonstolines`
#: gives back two separate loops, not one merged corridor) — points on those
#: loops still find a "nearest" shoreline point, just a spurious one, up to
#: 3 km away. Measured on a real run: median distance is 80-100 m, but the
#: tail runs out past 3000 m. 150 m is a wide margin over the 80 m offset —
#: wide enough for genuine shoreline movement, tight enough to drop the loop
#: artefacts.
PLAUSIBLE_DISTANCE_M = 150

EPR_FILTERED = OUT_DIR / "epr_filtered.gpkg"

#: Standard EPR bands (m/yr) — a judgement call, same shape DSAS studies in
#: the region use. Cited as a convention, not derived from this dataset.
EPR_BANDS = [
    (-999.0, -2.0, "strong erosion"),
    (-2.0, -0.5, "erosion"),
    (-0.5, 0.5, "stable"),
    (0.5, 2.0, "accretion"),
    (2.0, 999.0, "strong accretion"),
]


def _clip_step(scene: dict, band_key: str, out_key: str) -> dict:
    return {
        "algorithm_id": "gdal:cliprasterbyextent",
        "algorithm_name": "Clip raster by extent",
        "plain": f"Cut the {band_key} band down to the Cuddalore stretch ({scene['date']}).",
        "parameters": {
            "INPUT": str(scene[band_key]),
            "PROJWIN": AOI_EXTENT,
            "OVERCRS": False,
            "NODATA": None,
            "OUTPUT": str(scene[out_key]),
        },
        "inputs": [str(scene[band_key])],
        "outputs": [str(scene[out_key])],
    }


def _mndwi_step(scene: dict) -> dict:
    return {
        "algorithm_id": "gdal:rastercalculator",
        "algorithm_name": "Raster calculator",
        "plain": f"Compute the water index (MNDWI) for {scene['date']}.",
        "parameters": {
            "INPUT_A": str(scene["green_clip"]),
            "BAND_A": 1,
            "INPUT_B": str(scene["swir1_clip"]),
            "BAND_B": 1,
            "FORMULA": "(A.astype(float)-B.astype(float))/(A.astype(float)+B.astype(float))",
            "NO_DATA": -9999,
            "RTYPE": 5,  # Float32
            "OUTPUT": str(scene["mndwi"]),
        },
        "inputs": [str(scene["green_clip"]), str(scene["swir1_clip"])],
        "outputs": [str(scene["mndwi"])],
    }


def _threshold_step(scene: dict) -> dict:
    return {
        "algorithm_id": "gdal:rastercalculator",
        "algorithm_name": "Raster calculator",
        "plain": f"Turn the water index into a plain water/land map for {scene['date']} "
                 f"(cutoff t = {MNDWI_THRESHOLD}).",
        "parameters": {
            "INPUT_A": str(scene["mndwi"]),
            "BAND_A": 1,
            "FORMULA": f"A>{MNDWI_THRESHOLD}",
            "NO_DATA": -9999,
            "RTYPE": 0,  # Byte
            "OUTPUT": str(scene["water_mask"]),
        },
        "inputs": [str(scene["mndwi"])],
        "outputs": [str(scene["water_mask"])],
    }


def _polygonize_step(scene: dict) -> dict:
    return {
        "algorithm_id": "gdal:polygonize",
        "algorithm_name": "Polygonize (raster to vector)",
        "plain": f"Turn the water/land map into shapes for {scene['date']}.",
        "parameters": {
            "INPUT": str(scene["water_mask"]),
            "BAND": 1,
            "FIELD": "is_water",
            "EIGHT_CONNECTEDNESS": True,
            "OUTPUT": str(scene["water_polygons"]),
        },
        "inputs": [str(scene["water_mask"])],
        "outputs": [str(scene["water_polygons"])],
    }


def _fix_geometries_step(scene: dict) -> dict:
    return {
        "algorithm_id": "native:fixgeometries",
        "algorithm_name": "Fix geometries",
        "plain": f"Repair a few sliver shapes left over from rasterizing {scene['date']}.",
        "parameters": {
            "INPUT": str(scene["water_polygons"]),
            "METHOD": 1,  # structure
            "OUTPUT": str(scene["water_polygons_fixed"]),
        },
        "inputs": [str(scene["water_polygons"])],
        "outputs": [str(scene["water_polygons_fixed"])],
    }


def _keep_water_step(scene: dict) -> dict:
    return {
        "algorithm_id": "native:extractbyattribute",
        "algorithm_name": "Extract by attribute",
        "plain": f"Keep only the wet shapes for {scene['date']} — drop dry land.",
        "parameters": {
            "INPUT": str(scene["water_polygons_fixed"]),
            "FIELD": "is_water",
            "OPERATOR": 0,  # =
            "VALUE": "1",
            "OUTPUT": str(scene["water_only"]),
        },
        "inputs": [str(scene["water_polygons_fixed"])],
        "outputs": [str(scene["water_only"])],
    }


def _keep_sea_step(scene: dict) -> dict:
    return {
        "algorithm_id": "native:extractbyexpression",
        "algorithm_name": "Extract by expression",
        "plain": f"Keep only the sea for {scene['date']} — drop inland ponds and paddy "
                 f"fields, which show up as \"water\" too but are not the coastline.",
        "parameters": {
            "INPUT": str(scene["water_only"]),
            "EXPRESSION": "$area = maximum($area)",
            "OUTPUT": str(scene["sea_polygon"]),
        },
        "inputs": [str(scene["water_only"])],
        "outputs": [str(scene["sea_polygon"])],
    }


def _boundary_step(scene: dict) -> dict:
    return {
        "algorithm_id": "native:polygonstolines",
        "algorithm_name": "Polygons to lines",
        "plain": f"Trace the land-water edge for {scene['date']}.",
        "parameters": {
            "INPUT": str(scene["sea_polygon"]),
            "OUTPUT": str(scene["boundary_lines"]),
        },
        "inputs": [str(scene["sea_polygon"])],
        "outputs": [str(scene["boundary_lines"])],
    }


def _merge_shorelines_step() -> dict:
    inputs = [str(s["boundary_lines"]) for s in SCENES]
    return {
        "algorithm_id": "native:mergevectorlayers",
        "algorithm_name": "Merge vector layers",
        "plain": "Put both years' coastlines on one layer.",
        "parameters": {
            "LAYERS": inputs,
            "CRS": CRS,
            "OUTPUT": str(SHORELINES_MERGED),
        },
        "inputs": inputs,
        "outputs": [str(SHORELINES_MERGED)],
    }


def _baseline_buffer_step() -> dict:
    return {
        "algorithm_id": "native:buffer",
        "algorithm_name": "Buffer",
        "plain": f"Draw a band {BASELINE_OFFSHORE_M} m either side of both coastlines, "
                 f"to build a reference line offshore of both.",
        "parameters": {
            "INPUT": str(SHORELINES_MERGED),
            "DISTANCE": BASELINE_OFFSHORE_M,
            "SEGMENTS": 8,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": True,
            "OUTPUT": str(BASELINE_BUFFER),
        },
        "inputs": [str(SHORELINES_MERGED)],
        "outputs": [str(BASELINE_BUFFER)],
    }


def _baseline_ring_step() -> dict:
    return {
        "algorithm_id": "native:polygonstolines",
        "algorithm_name": "Polygons to lines",
        "plain": "Trace the outer edge of that offshore band — the baseline transects "
                 "will be cast from.",
        "parameters": {
            "INPUT": str(BASELINE_BUFFER),
            "OUTPUT": str(BASELINE_RING),
        },
        "inputs": [str(BASELINE_BUFFER)],
        "outputs": [str(BASELINE_RING)],
    }


def _densify_baseline_step() -> dict:
    return {
        "algorithm_id": "native:densifygeometriesgivenaninterval",
        "algorithm_name": "Densify by interval",
        "plain": f"Add a point every {TRANSECT_SPACING_M} m along the baseline — one "
                 f"transect will be cast from each.",
        "parameters": {
            "INPUT": str(BASELINE_RING),
            "INTERVAL": TRANSECT_SPACING_M,
            "OUTPUT": str(BASELINE_DENSIFIED),
        },
        "inputs": [str(BASELINE_RING)],
        "outputs": [str(BASELINE_DENSIFIED)],
    }


def _extract_baseline_points_step() -> dict:
    # densifygeometriesgivenaninterval keeps the baseline as ONE line feature
    # with more vertices, not one feature per vertex — joinbynearest needs
    # separate point features to measure a distance at every one of them.
    return {
        "algorithm_id": "native:extractvertices",
        "algorithm_name": "Extract vertices",
        "plain": "Turn every one of those baseline points into its own measuring point.",
        "parameters": {
            "INPUT": str(BASELINE_DENSIFIED),
            "OUTPUT": str(BASELINE_POINTS),
        },
        "inputs": [str(BASELINE_DENSIFIED)],
        "outputs": [str(BASELINE_POINTS)],
    }


def _transect_step() -> dict:
    return {
        "algorithm_id": "native:transect",
        "algorithm_name": "Transect",
        "plain": f"Cast a line inland from every one of those points, {TRANSECT_LENGTH_M} m "
                 f"long, at right angles to the baseline.",
        "parameters": {
            "INPUT": str(BASELINE_DENSIFIED),
            "LENGTH": TRANSECT_LENGTH_M,
            "ANGLE": 90,
            "SIDE": 2,  # Both — the seaward arc's transects are the ones that will
                        # actually intersect a shoreline; the landward arc's simply won't.
            "OUTPUT": str(TRANSECTS_RAW),
        },
        "inputs": [str(BASELINE_DENSIFIED)],
        "outputs": [str(TRANSECTS_RAW)],
    }


def _join_nearest_step(input_path, shoreline_path, prefix: str, output_path) -> dict:
    return {
        "algorithm_id": "native:joinbynearest",
        "algorithm_name": "Join attributes by nearest",
        "plain": f"Measure, from every point on the offshore baseline, how far the "
                 f"{prefix.rstrip('_')} coastline is.",
        "parameters": {
            "INPUT": str(input_path),
            "INPUT_2": str(shoreline_path),
            "FIELDS_TO_COPY": [],
            "DISCARD_NONMATCHING": False,
            "PREFIX": prefix,
            "NEIGHBORS": 1,
            "MAX_DISTANCE": None,
            "OUTPUT": str(output_path),
        },
        "inputs": [str(input_path), str(shoreline_path)],
        "outputs": [str(output_path)],
    }


DIST_2015_FIELD = OUT_DIR / "dist_2015_field.gpkg"
DIST_2026_FIELD = OUT_DIR / "dist_2026_field.gpkg"


def _add_distance_field_step(input_path, output_path, field_name: str,
                              fx: str, fy: str, nx: str, ny: str, plain: str) -> dict:
    # NOT using joinbynearest's own "distance"/"distance_2" fields — on this
    # QGIS build they come back wrong by orders of magnitude (a few hundred
    # thousand "metres" for points whose matched nearest_x/y is genuinely
    # ~80 m away), while feature_x/y and nearest_x/y are correct. Computing
    # the distance by hand from those coordinates sidesteps whatever's wrong
    # inside the algorithm's own distance calculation.
    formula = f'sqrt(("{fx}" - "{nx}")^2 + ("{fy}" - "{ny}")^2)'
    return {
        "algorithm_id": "native:fieldcalculator",
        "algorithm_name": "Field calculator",
        "plain": plain,
        "parameters": {
            "INPUT": str(input_path),
            "FIELD_NAME": field_name,
            "FIELD_TYPE": 0,  # Decimal
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 4,
            "FORMULA": formula,
            "OUTPUT": str(output_path),
        },
        "inputs": [str(input_path)],
        "outputs": [str(output_path)],
    }


def _epr_step() -> dict:
    # Baseline is fixed and offshore, so the shore moving CLOSER to it means
    # it moved seaward (accretion); moving FARTHER means it retreated
    # (erosion) — hence (older - newer), not (newer - older).
    formula = f'("dist_2015_m" - "dist_2026_m") / {SEPARATION_YEARS}'
    return {
        "algorithm_id": "native:fieldcalculator",
        "algorithm_name": "Field calculator",
        "plain": "Work out the erosion/accretion rate at every point: how many metres "
                 "a year the coast moved, over the years between the two images.",
        "parameters": {
            "INPUT": str(DIST_2026_FIELD),
            "FIELD_NAME": "epr_m_per_yr",
            "FIELD_TYPE": 0,  # Decimal
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 4,
            "FORMULA": formula,
            "OUTPUT": str(EPR_RESULT),
        },
        "inputs": [str(DIST_2026_FIELD)],
        "outputs": [str(EPR_RESULT)],
    }


def _filter_plausible_step() -> dict:
    return {
        "algorithm_id": "native:extractbyexpression",
        "algorithm_name": "Extract by expression",
        "plain": f"Drop the points whose nearest coastline match is farther than "
                 f"{PLAUSIBLE_DISTANCE_M} m away on either date — those are on the "
                 f"baseline's landward side, not real transect locations.",
        "parameters": {
            "INPUT": str(EPR_RESULT),
            "EXPRESSION": f'"dist_2015_m" < {PLAUSIBLE_DISTANCE_M} AND '
                           f'"dist_2026_m" < {PLAUSIBLE_DISTANCE_M}',
            "OUTPUT": str(EPR_FILTERED),
        },
        "inputs": [str(EPR_RESULT)],
        "outputs": [str(EPR_FILTERED)],
    }


def _classify_step() -> dict:
    # CASE/WHEN over the standard bands (EPR_BANDS) — a plain nested if(),
    # since QGIS expressions don't take a table lookup for vector fields the
    # way native:reclassifybytable does for rasters.
    expr = '"epr_m_per_yr"'
    formula = "'unknown'"
    for lo, hi, label in reversed(EPR_BANDS):
        formula = f"if({expr} >= {lo} AND {expr} < {hi}, '{label}', {formula})"
    return {
        "algorithm_id": "native:fieldcalculator",
        "algorithm_name": "Field calculator",
        "plain": "Label each point strong erosion / erosion / stable / accretion / "
                 "strong accretion, using the standard bands.",
        "parameters": {
            "INPUT": str(EPR_FILTERED),
            "FIELD_NAME": "classification",
            "FIELD_TYPE": 2,  # Text
            "FIELD_LENGTH": 20,
            "FIELD_PRECISION": 0,
            "FORMULA": formula,
            "OUTPUT": str(EPR_RESULT.with_name("epr_classified.gpkg")),
        },
        "inputs": [str(EPR_RESULT)],
        "outputs": [str(EPR_RESULT.with_name("epr_classified.gpkg"))],
    }


def build_steps() -> list[dict]:
    """Protocol §4: per-date shoreline extraction (steps 1-4), then baseline
    and transects (steps 5-8), built once from both dates together.
    Intersection + EPR (steps 9-10) come once the transect geometry itself is
    inspected — the schema native:transect/native:lineintersections produce
    isn't guessed at, it's read off a real run.
    """
    steps: list[dict] = []
    for scene in SCENES:
        steps.append(_clip_step(scene, "green", "green_clip"))
        steps.append(_clip_step(scene, "swir1", "swir1_clip"))
        steps.append(_mndwi_step(scene))
        steps.append(_threshold_step(scene))
        steps.append(_polygonize_step(scene))
        steps.append(_fix_geometries_step(scene))
        steps.append(_keep_water_step(scene))
        steps.append(_keep_sea_step(scene))
        steps.append(_boundary_step(scene))
    steps.append(_merge_shorelines_step())
    steps.append(_baseline_buffer_step())
    steps.append(_baseline_ring_step())
    steps.append(_densify_baseline_step())
    steps.append(_transect_step())
    steps.append(_extract_baseline_points_step())
    steps.append(_join_nearest_step(
        BASELINE_POINTS, SCENES[0]["boundary_lines"], "d2015_", DIST_TO_2015))
    steps.append(_join_nearest_step(
        DIST_TO_2015, SCENES[1]["boundary_lines"], "d2026_", DIST_TO_BOTH))
    steps.append(_add_distance_field_step(
        DIST_TO_BOTH, DIST_2015_FIELD, "dist_2015_m",
        "feature_x", "feature_y", "nearest_x", "nearest_y",
        "Work out how far the 2015 coastline really is from each baseline point."))
    steps.append(_add_distance_field_step(
        DIST_2015_FIELD, DIST_2026_FIELD, "dist_2026_m",
        "feature_x_2", "feature_y_2", "nearest_x_2", "nearest_y_2",
        "Work out how far the 2026 coastline really is from each baseline point."))
    steps.append(_epr_step())
    steps.append(_filter_plausible_step())
    steps.append(_classify_step())
    return steps


STEPS = build_steps()

OUTPUT_PATHS = tuple(pathlib.Path(p) for step in STEPS for p in step["outputs"])


def describe() -> str:
    lines = ["Extract the 2015 and 2026 shorelines around Cuddalore.", ""]
    for index, step in enumerate(STEPS, start=1):
        lines.append(f"  {index}. {step['plain']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
