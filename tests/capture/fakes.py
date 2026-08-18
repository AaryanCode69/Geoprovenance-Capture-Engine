"""Stand-ins for the QGIS objects the capture layer receives.

RULES.md §6.1 — these tests run with no QGIS. That is possible because
capture/normalizer.py and capture/engine.py duck-type rather than importing
QGIS classes, which is also what makes them survive QGIS API drift.

The fakes below mimic the *shapes* the normalizer looks for. Where QGIS is
inconsistent — ``QgsVectorLayer.source()`` is a method,
``QgsProcessingFeatureSourceDefinition.source`` is an attribute — the fakes are
inconsistent in the same way, on purpose.
"""

from __future__ import annotations




# ---------------------------------------------------------------------------
# QGIS-shaped fakes
# ---------------------------------------------------------------------------

class FakeCrs:
    """QgsCoordinateReferenceSystem."""

    def __init__(self, authid="EPSG:4326", wkt=""):
        self._authid = authid
        self._wkt = wkt

    def authid(self):
        return self._authid

    def toWkt(self):  # noqa: N802 — QGIS name
        return self._wkt


class FakeDataProvider:
    """QgsVectorDataProvider / QgsRasterDataProvider."""

    def __init__(self, name="ogr", storage_type="ESRI Shapefile"):
        self._name = name
        self._storage = storage_type

    def name(self):
        return self._name

    def storageType(self):  # noqa: N802 — QGIS name
        return self._storage


class FakeVectorLayer:
    """QgsVectorLayer. ``source`` is a METHOD here, as in QGIS."""

    def __init__(self, source, crs="EPSG:4326", feature_count=0,
                 storage_type="ESRI Shapefile", provider_name="ogr"):
        self._source = source
        self._crs = FakeCrs(crs)
        self._count = feature_count
        self._provider = FakeDataProvider(provider_name, storage_type)

    def source(self):
        return self._source

    def publicSource(self):  # noqa: N802 — QGIS name
        return self._source

    def crs(self):
        return self._crs

    def dataProvider(self):  # noqa: N802 — QGIS name
        return self._provider

    def featureCount(self):  # noqa: N802 — QGIS name
        return self._count

    def name(self):
        return "a layer name that must not be mistaken for the source"


class FakeRasterLayer:
    def __init__(self, source, crs="EPSG:32643", bands=3, storage_type="GTiff",
                 pixel_size=(30.0, 30.0), width=1200, height=800):
        self._source = source
        self._crs = FakeCrs(crs)
        self._bands = bands
        self._provider = FakeDataProvider("gdal", storage_type)
        self._pixel_size = pixel_size
        self._width = width
        self._height = height

    def source(self):
        return self._source

    def crs(self):
        return self._crs

    def dataProvider(self):  # noqa: N802
        return self._provider

    def bandCount(self):  # noqa: N802 — QGIS name
        return self._bands

    def rasterUnitsPerPixelX(self):  # noqa: N802 — QGIS name
        return self._pixel_size[0]

    def rasterUnitsPerPixelY(self):  # noqa: N802 — QGIS name
        return self._pixel_size[1]

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeExpression:
    """QgsExpression. Spells it ``expression()``, where QgsProperty spells it
    ``expressionString()`` — the difference that sent it to repr() in A3."""

    def __init__(self, expression):
        self._expression = expression

    def expression(self):
        return self._expression


class FakeVariant:
    """QVariant. QGIS uses a null one for an unset optional parameter."""

    def __init__(self, is_null=True):
        self._is_null = is_null

    def isNull(self):  # noqa: N802 — Qt name
        return self._is_null


class Anonymous:
    """No QGIS-ish accessors at all, so flattening falls back to repr().

    Its default repr carries a memory address, which is exactly the thing that
    must not reach the dedup key.
    """


class FakeProperty:
    """QgsProperty — either an expression or a wrapped static value."""

    def __init__(self, expression="", static=None):
        self._expression = expression
        self._static = static

    def expressionString(self):  # noqa: N802 — QGIS name
        return self._expression

    def staticValue(self):  # noqa: N802 — QGIS name
        return self._static


class FakeSourceDefinition:
    """QgsProcessingFeatureSourceDefinition. ``source`` is an ATTRIBUTE."""

    def __init__(self, source_path, selected_only=False):
        self.source = FakeProperty(static=source_path)
        self.selectedFeaturesOnly = selected_only  # noqa: N815 — QGIS name


class FakeOutputDefinition:
    """QgsProcessingOutputLayerDefinition. ``sink`` is an ATTRIBUTE."""

    def __init__(self, sink_path):
        self.sink = FakeProperty(static=sink_path)


class Explosive:
    """Every access raises. §5.5 — flattening must survive this."""

    def __getattr__(self, name):
        raise RuntimeError(f"exploded on {name}")

    def __repr__(self):
        return "<Explosive>"


class Unreprable:
    """Even __repr__ raises. The worst case flattening has to survive."""

    def __getattr__(self, name):
        raise RuntimeError("nope")

    def __repr__(self):
        raise RuntimeError("repr also explodes")


class FakeAlgorithmDefinitions:
    """The parameter-name -> type map hooks.parameter_definitions() produces."""

    BUFFER = {"INPUT": "source", "OUTPUT": "sink", "DISTANCE": "distance",
              "SEGMENTS": "number", "DISSOLVE": "boolean"}
    CLIP = {"INPUT": "source", "OVERLAY": "source", "OUTPUT": "sink"}
