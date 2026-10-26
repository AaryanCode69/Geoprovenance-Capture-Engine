"""The case-study-1 workflow: shoreline change at Cuddalore, as QGIS Processing calls.

Imported by `run_in_qgis.py` (the baseline run, P2 and P3) — the steps are
defined once so every run executes exactly the same chain. Every step is one
`processing.run` call, so every step is captured by the plugin's run wrapper.

The chain (Fig. 7 of the manuscript):
    per date: clip both bands to the area of interest -> MNDWI (Xu 2006) from
    surface reflectance -> threshold -> polygonize -> keep land -> keep the
    mainland (largest land body) -> close channels narrower than 300 m ->
    drop interior lakes -> tag the source scene -> boundary lines -> clip off
    the map edge = the shoreline for that date.
    rates: keep the long pieces of the earlier shoreline, smooth and simplify
    them into a reference line -> densify at
    100 m -> transects -> intersect both shorelines -> nearest crossing per
    transect -> join -> End Point Rate -> class.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import processing

#: Landsat Collection 2 Level-2 surface reflectance scale and offset (USGS).
SR_SCALE, SR_OFFSET = 2.75e-05, -0.2
#: Area of interest in EPSG:32644 (from download.py's AOI, unsnapped).
CRS = "EPSG:32644"
#: Transect spacing and half-length.
SPACING_M = 100.0
TRANSECT_M = 1500.0
#: Inner buffer that strips the map-edge segments off the sea boundary.
EDGE_STRIP_M = 100.0
#: Morphological closing radius: water channels narrower than twice this
#: (rivers, backwaters) are filled, so the mainland's edge is the open coast.
OPENING_M = 150.0
#: Reference-line simplification tolerance before densifying, so transects are
#: spaced by SPACING_M rather than at every 30 m raster-staircase vertex.
SIMPLIFY_M = 150.0
#: Reference-line pieces shorter than this are not the coast (see transects()).
MIN_REFERENCE_PART_M = 2000.0
#: EPR class cut-offs, m/yr — a design choice of this case study, stated as such.
CLASSES = ((-2.0, "strong erosion"), (-0.5, "erosion"), (0.5, "stable"), (2.0, "accretion"))


def years_between(a: str, b: str) -> float:
    d0, d1 = dt.date.fromisoformat(a[:10]), dt.date.fromisoformat(b[:10])
    return (d1 - d0).days / 365.2425


def run(alg: str, params: dict) -> dict:
    """One captured step. Returns QGIS's result dict."""
    return processing.run(alg, params)


def aoi_layers(out: pathlib.Path, aoi_extent: str) -> tuple[str, str]:
    aoi = str(out / "aoi.gpkg")
    inner = str(out / "aoi_inner.gpkg")
    run("native:extenttolayer", {"INPUT": aoi_extent, "OUTPUT": aoi})
    run("native:buffer", {"INPUT": aoi, "DISTANCE": -EDGE_STRIP_M, "SEGMENTS": 5,
                          "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "MITER_LIMIT": 2,
                          "DISSOLVE": False, "SEPARATE_DISJOINT": False, "OUTPUT": inner})
    return aoi, inner


def shoreline(out: pathlib.Path, tag: str, green: str, swir: str, aoi_extent: str,
              inner: str, threshold: float, scene_id: str) -> str:
    """The shoreline for one date. Returns the path of its GeoPackage."""
    p = lambda name: str(out / f"{tag}_{name}")  # noqa: E731
    run("gdal:cliprasterbyextent", {"INPUT": green, "PROJWIN": aoi_extent, "OVERCRS": False,
                                    "DATA_TYPE": 0, "OUTPUT": p("green.tif")})
    run("gdal:cliprasterbyextent", {"INPUT": swir, "PROJWIN": aoi_extent, "OVERCRS": False,
                                    "DATA_TYPE": 0, "OUTPUT": p("swir.tif")})
    ga = f"(A*{SR_SCALE}{SR_OFFSET:+})"
    sb = f"(B*{SR_SCALE}{SR_OFFSET:+})"
    run("gdal:rastercalculator", {"INPUT_A": p("green.tif"), "BAND_A": 1,
                                  "INPUT_B": p("swir.tif"), "BAND_B": 1,
                                  "FORMULA": f"({ga}-{sb})/({ga}+{sb}+1e-9)",
                                  "RTYPE": 5, "EXTENT_OPT": 0, "OUTPUT": p("mndwi.tif")})
    run("gdal:rastercalculator", {"INPUT_A": p("mndwi.tif"), "BAND_A": 1,
                                  "FORMULA": f"(A>{threshold})*1",
                                  "RTYPE": 0, "EXTENT_OPT": 0, "OUTPUT": p("water.tif")})
    run("gdal:polygonize", {"INPUT": p("water.tif"), "BAND": 1, "FIELD": "DN",
                            "EIGHT_CONNECTEDNESS": False, "OUTPUT": p("water_poly.gpkg")})
    # The mainland: the largest body that is NOT water. Tracing the land rather
    # than the sea is what keeps offshore turbidity and cloud out of the
    # shoreline — those are separate bodies, never part of the mainland.
    run("native:extractbyattribute", {"INPUT": p("water_poly.gpkg"), "FIELD": "DN",
                                      "OPERATOR": 0, "VALUE": "0",
                                      "OUTPUT": p("land_only.gpkg")})
    run("native:fieldcalculator", {"INPUT": p("land_only.gpkg"), "FIELD_NAME": "area_m2",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 1,
                                   "FORMULA": "$area", "OUTPUT": p("land_area.gpkg")})
    run("native:extractbyexpression", {"INPUT": p("land_area.gpkg"),
                                       "EXPRESSION": '"area_m2" = maximum("area_m2")',
                                       "OUTPUT": p("mainland.gpkg")})
    # Morphological closing: fill water channels narrower than 2*OPENING_M
    # (rivers, backwaters) so the mainland's edge is the open coast.
    buffer = {"SEGMENTS": 8, "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "MITER_LIMIT": 2,
              "DISSOLVE": False, "SEPARATE_DISJOINT": False}
    run("native:buffer", {"INPUT": p("mainland.gpkg"), "DISTANCE": OPENING_M, **buffer,
                          "OUTPUT": p("mainland_grown.gpkg")})
    run("native:buffer", {"INPUT": p("mainland_grown.gpkg"), "DISTANCE": -OPENING_M, **buffer,
                          "OUTPUT": p("mainland_closed.gpkg")})
    run("native:deleteholes", {"INPUT": p("mainland_closed.gpkg"), "MIN_AREA": 0,
                               "OUTPUT": p("mainland_solid.gpkg")})
    run("native:fieldcalculator", {"INPUT": p("mainland_solid.gpkg"), "FIELD_NAME": "source_scene",
                                   "FIELD_TYPE": 2, "FIELD_LENGTH": 60, "FIELD_PRECISION": 0,
                                   "FORMULA": f"'{scene_id}'", "OUTPUT": p("mainland_tagged.gpkg")})
    run("native:polygonstolines", {"INPUT": p("mainland_tagged.gpkg"),
                                   "OUTPUT": p("mainland_lines.gpkg")})
    run("native:clip", {"INPUT": p("mainland_lines.gpkg"), "OVERLAY": inner,
                        "OUTPUT": p("shoreline.gpkg")})
    return p("shoreline.gpkg")


def transects(out: pathlib.Path, reference_shoreline: str) -> str:
    """Transects every SPACING_M along a smoothed reference line, with midpoints."""
    # The coast is one long line; short pieces are lakes or creeks touching the
    # map edge, and transects cast from them would not cross the coast at all.
    run("native:multiparttosingleparts", {"INPUT": reference_shoreline,
                                          "OUTPUT": str(out / "reference_parts.gpkg")})
    run("native:extractbyexpression", {"INPUT": str(out / "reference_parts.gpkg"),
                                       "EXPRESSION": f"$length > {MIN_REFERENCE_PART_M}",
                                       "OUTPUT": str(out / "reference_coast.gpkg")})
    run("native:smoothgeometry", {"INPUT": str(out / "reference_coast.gpkg"), "ITERATIONS": 3,
                                  "OFFSET": 0.25, "MAX_ANGLE": 180,
                                  "OUTPUT": str(out / "reference_smooth.gpkg")})
    run("native:simplifygeometries", {"INPUT": str(out / "reference_smooth.gpkg"), "METHOD": 0,
                                      "TOLERANCE": SIMPLIFY_M,
                                      "OUTPUT": str(out / "reference_line.gpkg")})
    run("native:densifygeometriesgivenaninterval", {"INPUT": str(out / "reference_line.gpkg"),
                                                    "INTERVAL": SPACING_M,
                                                    "OUTPUT": str(out / "reference_dense.gpkg")})
    run("native:transect", {"INPUT": str(out / "reference_dense.gpkg"), "LENGTH": TRANSECT_M,
                            "ANGLE": 90, "SIDE": 2, "OUTPUT": str(out / "transects_raw.gpkg")})
    run("native:fieldcalculator", {"INPUT": str(out / "transects_raw.gpkg"), "FIELD_NAME": "mx",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 3,
                                   "FORMULA": "x(line_interpolate_point($geometry, $length/2))",
                                   "OUTPUT": str(out / "transects_mx.gpkg")})
    run("native:fieldcalculator", {"INPUT": str(out / "transects_mx.gpkg"), "FIELD_NAME": "my",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 3,
                                   "FORMULA": "y(line_interpolate_point($geometry, $length/2))",
                                   "OUTPUT": str(out / "transects.gpkg")})
    return str(out / "transects.gpkg")


def crossings(out: pathlib.Path, tag: str, transect_layer: str, shoreline_layer: str) -> str:
    """For each transect, where it crosses the shoreline nearest the reference line."""
    p = lambda name: str(out / f"{tag}_{name}")  # noqa: E731
    run("native:lineintersections", {"INPUT": transect_layer, "INTERSECT": shoreline_layer,
                                     "INPUT_FIELDS": ["TR_ID", "mx", "my"],
                                     "INTERSECT_FIELDS": ["source_scene"],
                                     "OUTPUT": p("cross_all.gpkg")})
    run("native:addxyfields", {"INPUT": p("cross_all.gpkg"), "CRS": CRS, "PREFIX": "",
                               "OUTPUT": p("cross_xy.gpkg")})
    run("native:fieldcalculator", {"INPUT": p("cross_xy.gpkg"), "FIELD_NAME": "d_ref",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 3,
                                   "FORMULA": 'sqrt(("x"-"mx")^2 + ("y"-"my")^2)',
                                   "OUTPUT": p("cross_d.gpkg")})
    run("native:extractbyexpression", {"INPUT": p("cross_d.gpkg"),
                                       "EXPRESSION": '"d_ref" = minimum("d_ref", group_by:="TR_ID")',
                                       "OUTPUT": p("cross.gpkg")})
    return p("cross.gpkg")


def rates(out: pathlib.Path, early: str, late: str, years: float, name: str = "epr") -> str:
    """End Point Rate per transect, and its class. Returns the classified layer."""
    run("native:joinattributestable", {"INPUT": early, "FIELD": "TR_ID", "INPUT_2": late,
                                       "FIELD_2": "TR_ID", "FIELDS_TO_COPY": ["x", "y"],
                                       "METHOD": 1, "DISCARD_NONMATCHING": True,
                                       "PREFIX": "late_", "OUTPUT": str(out / f"{name}_pairs.gpkg")})
    # Sign: the coast here runs roughly north-south with the sea to the east,
    # so a later crossing further east is accretion. Stated in the manuscript.
    run("native:fieldcalculator", {"INPUT": str(out / f"{name}_pairs.gpkg"), "FIELD_NAME": "epr",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 4,
                                   "FORMULA": (f'if("late_x" > "x", 1, -1) * '
                                               f'sqrt(("late_x"-"x")^2 + ("late_y"-"y")^2) / {years}'),
                                   "OUTPUT": str(out / f"{name}.gpkg")})
    cases = " ".join(f"WHEN \"epr\" < {cut} THEN '{label}'" for cut, label in CLASSES)
    run("native:fieldcalculator", {"INPUT": str(out / f"{name}.gpkg"), "FIELD_NAME": "epr_class",
                                   "FIELD_TYPE": 2, "FIELD_LENGTH": 20, "FIELD_PRECISION": 0,
                                   "FORMULA": f"CASE {cases} ELSE 'strong accretion' END",
                                   "OUTPUT": str(out / f"{name}_classified.gpkg")})
    return str(out / f"{name}_classified.gpkg")
