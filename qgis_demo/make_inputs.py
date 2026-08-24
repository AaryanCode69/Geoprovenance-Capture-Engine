"""Build the three input datasets the demo workflow starts from.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    python qgis_demo/make_inputs.py        (or: make qgis-demo-inputs)

Writes, from the definitions in ``scenario.py``:

    qgis_demo/data/roads.shp           6 roads, as lines
    qgis_demo/data/city_boundary.gpkg  1 boundary, as an area
    qgis_demo/data/schools.shp         14 schools, as points

Two formats on purpose. The provenance record carries a ``format`` for every
file it knows about, and a demo where every file is the same format never shows
that column doing anything.

Deterministic: every byte is a pure function of ``scenario.py``. Re-running this
without editing the scenario rewrites identical files.
"""

from __future__ import annotations

import sys

from qgis_demo import geopkg, scenario, shapefile


def build_roads():
    geometries = [road["coords"] for road in scenario.ROADS]
    records = [{"name": road["name"], "kind": road["kind"]} for road in scenario.ROADS]
    return shapefile.write_shapefile(
        scenario.ROADS_SHP,
        shapefile.SHAPE_POLYLINE,
        geometries,
        fields=[("name", 24), ("kind", 12)],
        records=records,
    )


def build_schools():
    geometries = [[(s["lon"], s["lat"])] for s in scenario.SCHOOLS]
    records = [{"name": s["name"], "kind": s["kind"]} for s in scenario.SCHOOLS]
    return shapefile.write_shapefile(
        scenario.SCHOOLS_SHP,
        shapefile.SHAPE_POINT,
        geometries,
        fields=[("name", 24), ("kind", 12)],
        records=records,
    )


def build_boundary():
    layer = geopkg.Layer(
        name="city_boundary",
        geometry_type="POLYGON",
        fields=[geopkg.Field("name"), geopkg.Field("kind")],
        rows=[(geopkg.wkb_polygon([scenario.CITY_BOUNDARY]),
               {"name": "City limits", "kind": "administrative"})],
        description="The demo city boundary",
    )
    return geopkg.write_geopackage(scenario.BOUNDARY_GPKG, [layer])


def main() -> int:
    scenario.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for build in (build_roads, build_boundary, build_schools):
        path = build()
        print(f"  wrote {path.relative_to(scenario.REPO_ROOT)}  "
              f"({path.stat().st_size} bytes)")
    print()
    print(scenario.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
