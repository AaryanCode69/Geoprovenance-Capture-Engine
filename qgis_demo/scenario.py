"""The demo workflow, defined once and used by everything.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

The question the workflow answers
    "Which schools sit within about 500 m of a main road, inside the city
    boundary?" — four Processing steps over three small datasets around
    Bengaluru.

Why the definition lives in one file
    Three things consume it: ``make_inputs.py`` builds the input datasets from
    it, ``run_in_qgis.py`` runs the four steps inside a real QGIS from it, and
    ``replay.py`` feeds the same four steps through the capture engine on a
    machine with no QGIS. If any two of those drifted apart the demo would be
    showing something the code did not do, which RULES.md §7.9 treats as a
    failed gate. One definition, three readers, no drift.

Why the fixtures are not reused instead
    ``tests/fixtures/`` is a frozen, committed contract that Person B and Person
    C consume (RULES.md §3.4, §10.3), and its dataset paths are deliberately
    mostly nonexistent so Person C gets a "the input is gone" case to audit.
    That makes it exactly the wrong thing to draw a map from, and the wrong
    thing to edit. Nothing here touches it.

Coordinates
    WGS 84 (EPSG:4326), so the buffer distance is in degrees. 0.0045° of
    latitude is about 500 m at this latitude, which is close enough for a demo
    and is described to reviewers as "about 500 m" rather than as an exact
    figure.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "qgis_demo"
DATA_DIR = DEMO_ROOT / "data"
PROJECT_DIR = DEMO_ROOT / "project"
DB_PATH = DEMO_ROOT / "provenance.db"

CRS = "EPSG:4326"

#: About 500 m at 13°N, expressed in the layer's own units (degrees).
BUFFER_DEGREES = 0.0045


# ---------------------------------------------------------------------------
# Input datasets
# ---------------------------------------------------------------------------

#: The city boundary — one polygon, deliberately smaller than the road network
#: so that step 2 (clip) visibly removes something.
CITY_BOUNDARY = [
    (77.520, 12.900),
    (77.700, 12.905),
    (77.715, 13.030),
    (77.560, 13.055),
    (77.505, 12.985),
    (77.520, 12.900),
]

#: Six arterial roads, as open polylines. Two of them run outside the boundary
#: at one end, which is what makes the clip step interesting to look at.
ROADS: list[dict] = [
    {"name": "Outer Ring Road", "kind": "arterial",
     "coords": [(77.500, 12.930), (77.560, 12.945), (77.640, 12.960), (77.720, 12.990)]},
    {"name": "Hosur Road", "kind": "arterial",
     "coords": [(77.600, 12.880), (77.610, 12.940), (77.615, 13.000), (77.620, 13.060)]},
    {"name": "Bannerghatta Road", "kind": "arterial",
     "coords": [(77.575, 12.890), (77.585, 12.955), (77.590, 13.010)]},
    {"name": "Old Airport Road", "kind": "arterial",
     "coords": [(77.530, 12.995), (77.610, 13.000), (77.690, 13.010)]},
    {"name": "Magadi Road", "kind": "secondary",
     "coords": [(77.510, 13.010), (77.560, 13.020), (77.605, 13.028)]},
    {"name": "Sarjapur Road", "kind": "secondary",
     "coords": [(77.640, 12.905), (77.665, 12.945), (77.690, 12.985)]},
]

#: Fourteen schools. Some sit on a road, some are well away from one — so the
#: last step actually filters, and a reviewer can see why each point survived.
SCHOOLS: list[dict] = [
    {"name": "Cantonment High",        "kind": "secondary", "lon": 77.612, "lat": 12.998},
    {"name": "Jayanagar Primary",      "kind": "primary",   "lon": 77.585, "lat": 12.956},
    {"name": "Koramangala Public",     "kind": "secondary", "lon": 77.617, "lat": 12.941},
    {"name": "Indiranagar Girls",      "kind": "secondary", "lon": 77.641, "lat": 13.001},
    {"name": "Rajajinagar Model",      "kind": "primary",   "lon": 77.556, "lat": 13.019},
    {"name": "Whitefield Junior",      "kind": "primary",   "lon": 77.705, "lat": 12.992},
    {"name": "Basavanagudi Central",   "kind": "secondary", "lon": 77.574, "lat": 12.941},
    {"name": "Malleshwaram East",      "kind": "primary",   "lon": 77.566, "lat": 13.030},
    {"name": "Hebbal Lakeside",        "kind": "secondary", "lon": 77.590, "lat": 13.048},
    {"name": "Yelahanka Outpost",      "kind": "primary",   "lon": 77.530, "lat": 13.070},
    {"name": "Bommanahalli South",     "kind": "primary",   "lon": 77.618, "lat": 12.900},
    {"name": "Sarjapur Woods",         "kind": "secondary", "lon": 77.668, "lat": 12.947},
    {"name": "Kengeri Far West",       "kind": "primary",   "lon": 77.480, "lat": 12.915},
    {"name": "Banashankari North",     "kind": "secondary", "lon": 77.561, "lat": 12.972},
]

ROADS_SHP = DATA_DIR / "roads.shp"
BOUNDARY_GPKG = DATA_DIR / "city_boundary.gpkg"
SCHOOLS_SHP = DATA_DIR / "schools.shp"

INPUT_PATHS = (ROADS_SHP, BOUNDARY_GPKG, SCHOOLS_SHP)


# ---------------------------------------------------------------------------
# The four steps
# ---------------------------------------------------------------------------

OUT_DIR = DATA_DIR / "derived"

ROADS_BUFFERED = OUT_DIR / "roads_buffered.gpkg"
ROADS_IN_CITY = OUT_DIR / "roads_in_city.gpkg"
SCHOOLS_NEAR_ROADS = OUT_DIR / "schools_near_roads.gpkg"
ROAD_CORRIDOR = OUT_DIR / "road_corridor.gpkg"

#: Each step is a real QGIS Processing algorithm, with the parameters QGIS
#: itself would receive. ``plain`` is the sentence a reviewer reads (RULES.md
#: §7.5 — no jargon anywhere a reviewer looks).
STEPS: list[dict] = [
    {
        "algorithm_id": "native:buffer",
        "algorithm_name": "Buffer",
        "provider": "qgis",
        "plain": "Draw a band about 500 m wide either side of every road.",
        "parameters": {
            "INPUT": str(ROADS_SHP),
            "DISTANCE": BUFFER_DEGREES,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": str(ROADS_BUFFERED),
        },
        "inputs": [str(ROADS_SHP)],
        "outputs": [str(ROADS_BUFFERED)],
    },
    {
        "algorithm_id": "native:clip",
        "algorithm_name": "Clip",
        "provider": "qgis",
        "plain": "Cut those bands back to the city boundary.",
        "parameters": {
            "INPUT": str(ROADS_BUFFERED),
            "OVERLAY": str(BOUNDARY_GPKG),
            "OUTPUT": str(ROADS_IN_CITY),
        },
        "inputs": [str(ROADS_BUFFERED), str(BOUNDARY_GPKG)],
        "outputs": [str(ROADS_IN_CITY)],
    },
    {
        "algorithm_id": "native:extractbylocation",
        "algorithm_name": "Extract by location",
        "provider": "qgis",
        "plain": "Keep only the schools that fall inside those bands.",
        "parameters": {
            "INPUT": str(SCHOOLS_SHP),
            "PREDICATE": [0],          # intersects
            "INTERSECT": str(ROADS_IN_CITY),
            "OUTPUT": str(SCHOOLS_NEAR_ROADS),
        },
        "inputs": [str(SCHOOLS_SHP), str(ROADS_IN_CITY)],
        "outputs": [str(SCHOOLS_NEAR_ROADS)],
    },
    {
        "algorithm_id": "native:dissolve",
        "algorithm_name": "Dissolve",
        "provider": "qgis",
        "plain": "Merge the overlapping bands into one road corridor.",
        "parameters": {
            "INPUT": str(ROADS_IN_CITY),
            "FIELD": [],
            "SEPARATE_DISJOINT": False,
            "OUTPUT": str(ROAD_CORRIDOR),
        },
        "inputs": [str(ROADS_IN_CITY)],
        "outputs": [str(ROAD_CORRIDOR)],
    },
]

OUTPUT_PATHS = tuple(pathlib.Path(p) for step in STEPS for p in step["outputs"])


def describe() -> str:
    """The workflow in the words a reviewer hears."""
    lines = ["Which schools are within about 500 m of a main road, inside the city?", ""]
    for index, step in enumerate(STEPS, start=1):
        lines.append(f"  {index}. {step['plain']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
