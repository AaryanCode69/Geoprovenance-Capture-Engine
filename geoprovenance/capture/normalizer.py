"""Event normalizer — raw QGIS objects in, the frozen event dict out.

Owner: Person A.  Sub-phase: A3 (working), hardened in A4.
Contract: docs/CONTRACT_event.md + schemas/event.schema.json.

    THIS MODULE IMPORTS NO QGIS, DELIBERATELY.

Two reasons, and the second is the important one:

  1. It makes the riskiest code in the component testable on a machine with no
     QGIS. Parameter serialisation is "the single biggest source of crashes in
     this component" (PERSON_A.md §A4), so it needs real tests, not hopeful
     ones.

  2. Duck typing survives QGIS API drift. `QgsHistoryProviderRegistry` has
     already changed signature across releases (research doc §12 risk 7), and
     `isinstance` checks against a moving class hierarchy are exactly how a
     plugin ends up pinned to one QGIS version. Asking "does this object have
     authid()?" keeps working when the class is moved or renamed.

Rules implemented here
    §5.5  Serialisation NEVER raises. Unknown types fall back to repr().
    §5.6  Output paths resolve from a path string, a layer id, or a layer
          object; unresolvable becomes None, never a guess.
    §5.7  CRS from the layer, stored as authid(); WKT only when no authid.
    §5.8  Format from the provider/driver name, NOT the file extension.
    §3.3  Memory / temporary / /vsimem/ layers get path=None but keep
          layer_type, so Person B knows not to fingerprint them.
    §3.3  Layer-valued parameters are lifted into inputs/outputs; scalars stay
          in `parameters`.
    §5.9  The dedup key both channels agree on.

A4 hardening
    The awkward-type table below is exhaustive as far as the QGIS types this
    component has been shown to receive. Three things it now gets right that
    A3 did not:

      - repr() fallbacks are address-free, because dedup_key hashes them. A
        raw repr() embeds `0x7f3c…`, so the same execution seen on two
        channels hashed differently and §5.9's first-channel-wins rule never
        fired — the job was written twice.
      - `selectedFeaturesOnly` survives. Without it, "buffer the whole layer"
        and "buffer only the selection" recorded identically AND collided on
        the dedup key, so the second run was discarded as a duplicate.
      - Raster layers carry band count, pixel size and dimensions, closing
        the OPEN item in docs/CONTRACT_event.md.
"""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import hashlib
import json
import re
import uuid
from typing import Any

#: Prefixes and sentinels that mean "there is no file on disk" (§3.3).
NON_FILE_PREFIXES = ("memory:", "/vsimem/", "/vsizip/", "/vsicurl/", "vsimem/")
NON_FILE_SENTINELS = ("TEMPORARY_OUTPUT", "memory", "")

#: Recursion guard for flatten_value. QGIS parameter values are shallow in
#: practice; anything deeper is a structure we do not understand and repr() is
#: a better answer than a stack overflow.
MAX_DEPTH = 6

#: §5.9 — both channels must land in the same bucket for the same execution.
DEDUP_BUCKET_MS = 100

#: §5.8 — stable format names, keyed by the provider or driver name QGIS
#: reports, NEVER by file extension. Only specific driver names are translated:
#: `ogr` and `gdal` are generic container providers and say nothing about the
#: format, so they are left alone rather than mapped to a guess. An
#: unrecognised name passes through unchanged (§5.6 — never invent).
PROVIDER_FORMATS = {
    "esri shapefile": "Shapefile",
    "gpkg": "GeoPackage",
    "geopackage": "GeoPackage",
    "gtiff": "GeoTIFF",
    "memory": "Memory",
    "delimitedtext": "Delimited text",
    "postgres": "PostGIS",
    "spatialite": "SpatiaLite",
    "wfs": "WFS",
    "wms": "WMS",
}

#: Marks a source that covers only the layer's selected features. Written in
#: GDAL/OGR's `|key=value` selector style so classify_path strips it back off
#: the same way it strips `|layername=` — the flag belongs in the recorded
#: parameters, never in entities.file_path.
SELECTED_FEATURES_SUFFIX = "|selectedFeaturesOnly=yes"

#: Layer-entry fields merge_results may fill in from the algorithm's results.
MERGEABLE_FIELDS = (
    "format", "crs", "feature_count", "band_count", "pixel_size", "width", "height",
)

#: A CPython repr embeds the object's address: `<QgsProperty object at 0x7f3c…>`.
#: dedup_key hashes flattened parameters, so leaving the address in makes the
#: same execution hash differently on each channel and silently defeats §5.9.
_MEMORY_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


# ---------------------------------------------------------------------------
# parameter flattening (§5.5)
# ---------------------------------------------------------------------------

def _stable_repr(value: Any) -> str:
    """``repr(value)`` with memory addresses masked out. Never raises.

    The masking is not cosmetic. ``dedup_key`` hashes the flattened parameters,
    and an unrecognised type reaches it as a repr. Two channels observe the
    same execution holding the same object at the same address, but a re-run —
    or a second interpreter-level allocation — moves it, so an unmasked repr
    made the hash unstable and §5.9's "first channel wins, second corroborates"
    degenerated into writing the job twice.
    """
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 — a broken __repr__ is still not our problem
        try:
            return f"<unserialisable {type(value).__name__}>"
        except Exception:  # noqa: BLE001 — §5.5 is absolute
            return "<unserialisable>"
    return _MEMORY_ADDRESS.sub("0x…", text)


def _call_or_get(obj: Any, name: str):
    """Read ``obj.name``, calling it when it is a method. Returns (ok, value).

    QGIS is inconsistent about this — ``QgsProcessingFeatureSourceDefinition``
    exposes ``source`` as an attribute while ``QgsVectorLayer`` exposes
    ``source()`` as a method — so both shapes are accepted.
    """
    try:
        attribute = getattr(obj, name)
    except Exception:  # noqa: BLE001 — a property getter can raise
        return False, None
    try:
        return True, (attribute() if callable(attribute) else attribute)
    except Exception:  # noqa: BLE001 — §5.5, never raise
        return False, None


def _extract_qgis_like(value: Any):
    """Recognise a QGIS value object by shape. Returns (handled, plain value).

    Order matters. A layer has both ``source()`` and ``name()``; a CRS has the
    very distinctive ``authid()``. Most specific first.
    """
    # QgsCoordinateReferenceSystem — §5.7: authid first, WKT only if there is none.
    ok, authid = _call_or_get(value, "authid")
    if ok and isinstance(authid, str):
        if authid:
            return True, authid
        ok_wkt, wkt = _call_or_get(value, "toWkt")
        if ok_wkt and isinstance(wkt, str) and wkt:
            return True, wkt
        return True, None

    # QgsGeometry / QgsReferencedGeometry
    ok, wkt = _call_or_get(value, "asWkt")
    if ok and isinstance(wkt, str):
        return True, wkt

    # QVariant — QGIS uses a null QVariant for an unset optional parameter.
    # Checked after the two branches above because QgsGeometry also has
    # isNull(); a null geometry is better described by its (empty) WKT.
    ok, is_null = _call_or_get(value, "isNull")
    if ok and is_null is True:
        return True, None

    # QgsProperty — an expression, or a static value wrapped in one.
    ok, expression = _call_or_get(value, "expressionString")
    if ok and isinstance(expression, str):
        if expression:
            return True, expression
        ok_static, static = _call_or_get(value, "staticValue")
        if ok_static:
            return True, flatten_value(static)
        return True, None

    # QgsExpression spells the same idea differently. Without this it fell
    # through to repr() — and therefore into the dedup instability above.
    ok, expression = _call_or_get(value, "expression")
    if ok and isinstance(expression, str) and expression:
        return True, expression

    # QgsProcessingFeatureSourceDefinition (.source) and
    # QgsProcessingOutputLayerDefinition (.sink) both wrap a QgsProperty.
    for attribute in ("source", "sink"):
        ok, inner = _call_or_get(value, attribute)
        if ok and inner is not None and not isinstance(inner, (int, float, bool)):
            unwrapped = flatten_value(inner)
            # "Buffer the whole layer" and "buffer only the selection" are
            # different runs producing different data. Dropping this flag made
            # them record identically AND collide on the dedup key, so the
            # second was silently discarded as a duplicate of the first.
            ok_selected, selected_only = _call_or_get(value, "selectedFeaturesOnly")
            if ok_selected and selected_only and isinstance(unwrapped, str):
                return True, f"{unwrapped}{SELECTED_FEATURES_SUFFIX}"
            return True, unwrapped

    # QgsRectangle and friends.
    ok, text = _call_or_get(value, "toString")
    if ok and isinstance(text, str):
        return True, text

    return False, None


def flatten_value(value: Any, _depth: int = 0) -> Any:
    """A JSON-safe representation of any QGIS parameter value.

    §5.5 [HARD] — this never raises. QGIS hands the normalizer
    ``QgsProcessingFeatureSourceDefinition``, ``QgsCoordinateReferenceSystem``,
    ``QgsProperty`` and worse; an unrecognised type falls back to ``repr()``
    rather than taking down the user's processing run.

    Person B can rely on ``json.dumps(event)`` never raising because of this.
    """
    try:
        if value is None or isinstance(value, (bool, int, str)):
            return value

        if isinstance(value, float):
            # NaN and Infinity are not valid JSON, whatever json.dumps allows.
            return value if value == value and abs(value) != float("inf") else repr(value)

        if _depth >= MAX_DEPTH:
            return _stable_repr(value)

        # QGIS 3.30+ hands out real Python enums (Qgis.ProcessingSourceType and
        # friends) where older releases used plain ints.
        if isinstance(value, enum.Enum):
            return flatten_value(value.value, _depth + 1)

        if isinstance(value, decimal.Decimal):
            number = float(value)
            return number if number == number and abs(number) != float("inf") else str(value)

        if isinstance(value, dict):
            return {str(k): flatten_value(v, _depth + 1) for k, v in value.items()}

        if isinstance(value, (list, tuple, set, frozenset)):
            return [flatten_value(v, _depth + 1) for v in value]

        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", "replace")

        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            return value.isoformat()

        if hasattr(value, "__fspath__"):
            return str(value)

        handled, extracted = _extract_qgis_like(value)
        if handled:
            return extracted

        return _stable_repr(value)
    except Exception:  # noqa: BLE001 — §5.5 is absolute
        return _stable_repr(value)


def flatten_parameters(parameters: Any) -> dict[str, Any]:
    """Flatten a whole parameter dict. Always returns a dict, never raises."""
    if not isinstance(parameters, dict):
        return {"_parameters": flatten_value(parameters)}
    return {str(key): flatten_value(value) for key, value in parameters.items()}


# ---------------------------------------------------------------------------
# paths and layers (§3.3, §5.6, §5.7, §5.8)
# ---------------------------------------------------------------------------

def _resolve_text(raw: Any) -> str | None:
    """A path-ish string for ``raw``, or None. Deliberately NOT repr().

    ``flatten_value`` falls back to ``repr()`` because a parameter record is
    better with ``<QgsProperty object at 0x…>`` in it than missing. A *path* is
    not: writing that repr into ``entities.file_path`` invents a file that
    never existed and puts a phantom node in Person C's graph. §5.6 — an
    unresolvable reference becomes None, never a guess.
    """
    if isinstance(raw, str):
        return raw
    try:
        # NOTE: hasattr only swallows AttributeError. A QGIS object whose
        # __getattr__ raises anything else propagates straight through it,
        # which is how this function learned to need a try block at all.
        if hasattr(raw, "__fspath__"):
            return str(raw)
        handled, value = _extract_qgis_like(raw)
        return value if handled and isinstance(value, str) else None
    except Exception:  # noqa: BLE001 — §5.5, never raise
        return None


def classify_path(raw: Any) -> str | None:
    """The filesystem path for a layer reference, or None if it has no file.

    §3.3 — memory layers, ``TEMPORARY_OUTPUT`` and the GDAL virtual filesystems
    have no bytes on disk. They get ``path=None`` and Person B must not attempt
    to fingerprint them.

    §5.6 — an unresolvable reference becomes None, never a guess.
    """
    if raw is None:
        return None
    text = _resolve_text(raw)
    if text is None:
        return None

    text = text.strip()
    if text in NON_FILE_SENTINELS:
        return None
    if any(text.startswith(prefix) for prefix in NON_FILE_PREFIXES):
        return None
    # A repr that leaked in from somewhere else is not a path either.
    if text.startswith("<") and text.endswith(">"):
        return None

    # GDAL/OGR sublayer syntax: "GPKG:/path/to/file.gpkg:layername",
    # "/path/to/file.gpkg|layername=roads". Keep the file, drop the selector.
    for separator in ("|layername=", "|layerid=", "|subset=", "|selectedFeaturesOnly="):
        if separator in text:
            text = text.split(separator, 1)[0]
    return text or None


def _whole_number(value: Any, accessor: str) -> int | None:
    """A non-negative int from ``value.accessor()``, or None. Never raises.

    ``isinstance(True, int)`` is True in Python, so booleans are excluded
    explicitly — a provider that answers True to bandCount() must not be
    recorded as a one-band raster.
    """
    ok, number = _call_or_get(value, accessor)
    if ok and isinstance(number, int) and not isinstance(number, bool) and number >= 0:
        return number
    return None


def _finite_number(value: Any, accessor: str) -> float | None:
    """A finite float from ``value.accessor()``, or None. Never raises."""
    ok, number = _call_or_get(value, accessor)
    if not ok or isinstance(number, bool) or not isinstance(number, (int, float)):
        return None
    number = float(number)
    return number if number == number and abs(number) != float("inf") else None


def _canonical_format(name: str) -> str:
    """A stable format name for a provider or driver name (§5.8)."""
    return PROVIDER_FORMATS.get(name.strip().lower(), name)


def describe_layer(param_key: str, value: Any, *, layer_type: str = "unknown") -> dict:
    """One entry for the event's ``inputs`` or ``outputs`` list.

    ``value`` may be a path string, a layer object, or a
    ``QgsProcessing*Definition`` wrapper — §5.6 requires all three to resolve.
    """
    entry = {
        "param": str(param_key),
        "path": None,
        "format": None,
        "crs": None,
        "layer_type": layer_type,
        # Vector fields. Every key is always present, whatever the layer type,
        # so Person B never has to test for presence — only for None.
        "feature_count": None,
        # Raster fields (docs/CONTRACT_event.md decision, closed in A4).
        "band_count": None,
        "pixel_size": None,
        "width": None,
        "height": None,
    }
    if value is None:
        return entry

    # A layer object knows more about itself than a path string does.
    source = None
    for attribute in ("publicSource", "source"):
        ok, candidate = _call_or_get(value, attribute)
        if ok and isinstance(candidate, str) and candidate:
            source = candidate
            break
    # No source accessor: hand the raw object to classify_path, which resolves
    # it without the repr() fallback (§5.6).
    entry["path"] = classify_path(source if source is not None else value)

    ok, crs = _call_or_get(value, "crs")
    if ok and crs is not None:
        entry["crs"] = flatten_value(crs)  # _extract_qgis_like gives us authid()

    # §5.8 — the provider/driver name, NOT the file extension. A .gpkg can hold
    # vector or raster, so the extension tells you nothing reliable.
    ok, provider = _call_or_get(value, "dataProvider")
    if ok and provider is not None:
        ok_name, name = _call_or_get(provider, "name")
        if ok_name and isinstance(name, str) and name:
            entry["format"] = _canonical_format(name)
        # The driver is more specific than the provider — "ogr" tells you
        # nothing, "ESRI Shapefile" tells you everything — so it wins.
        ok_driver, driver = _call_or_get(provider, "storageType")
        if ok_driver and isinstance(driver, str) and driver:
            entry["format"] = _canonical_format(driver)

    count = _whole_number(value, "featureCount")
    if count is not None:
        entry["feature_count"] = count
        if entry["layer_type"] == "unknown":
            entry["layer_type"] = "vector"

    bands = _whole_number(value, "bandCount")
    if bands is not None:
        entry["band_count"] = bands
        if entry["layer_type"] == "unknown":
            entry["layer_type"] = "raster"

        pixel_x = _finite_number(value, "rasterUnitsPerPixelX")
        pixel_y = _finite_number(value, "rasterUnitsPerPixelY")
        if pixel_x is not None and pixel_y is not None:
            entry["pixel_size"] = [pixel_x, pixel_y]
        # width()/height() exist on QgsRasterLayer but not QgsVectorLayer, so
        # they are only asked for once bandCount() has identified a raster.
        entry["width"] = _whole_number(value, "width")
        entry["height"] = _whole_number(value, "height")

    return entry


# ---------------------------------------------------------------------------
# deduplication (§5.9)
# ---------------------------------------------------------------------------

def _bucket_timestamp(started_at: str) -> str:
    """Round an ISO timestamp down to a DEDUP_BUCKET_MS boundary.

    The two channels observe the same execution microseconds apart, so an exact
    timestamp match would never fire. The bucket is what makes them agree.
    """
    try:
        moment = dt.datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return str(started_at)
    step = DEDUP_BUCKET_MS * 1000
    return moment.replace(microsecond=(moment.microsecond // step) * step).isoformat()


def dedup_key(algorithm_id: str, parameters: Any, started_at: str) -> str:
    """The key both capture channels compute for one execution (§5.9).

    First channel to arrive inserts; the second finds this key already present
    and increments the corroboration counter instead. Keeping that counter is
    what produces the publishable "the hook caught 98%, the history channel
    caught the other 2%" result (§8.3).
    """
    # default=_stable_repr, not default=repr: anything reaching the encoder's
    # fallback would otherwise carry a memory address into the digest and make
    # this key differ between two observations of one execution.
    canonical = json.dumps(
        flatten_parameters(parameters), sort_keys=True, default=_stable_repr
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{algorithm_id}|{digest}|{_bucket_timestamp(started_at)}"


# ---------------------------------------------------------------------------
# the event dict (docs/CONTRACT_event.md)
# ---------------------------------------------------------------------------

#: Parameter definition types QGIS uses for layer-valued inputs and outputs.
#: Anything not listed stays a scalar in `parameters` (§3.3).
INPUT_PARAM_TYPES = frozenset({
    "source", "layer", "vector", "raster", "mesh", "multilayer", "maplayer",
    "pointcloud", "annotation", "vectortile",
})
OUTPUT_PARAM_TYPES = frozenset({
    # QgsProcessingParameterDefinition types
    "sink", "vectorDestination", "rasterDestination", "fileDestination",
    "folderDestination", "pointCloudDestination", "vectorTileDestination",
    # QgsProcessingOutputDefinition types that denote a DATASET. outputNumber,
    # outputString, outputBoolean and outputHtml are scalars and stay in
    # `parameters` — a count is not a file.
    "outputVector", "outputRaster", "outputLayer", "outputFile", "outputFolder",
    "outputMultilayer", "outputPointCloud", "outputVectorTile",
})


def split_parameters(parameters: dict, definitions: dict[str, str]) -> tuple[dict, list, list]:
    """Separate layer-valued parameters from scalar ones (§3.3).

    ``definitions`` maps parameter name -> QGIS parameter type string, as
    reported by ``QgsProcessingParameterDefinition.type()``. A parameter with
    no definition is treated as a scalar: guessing that an unknown parameter is
    a layer would put a made-up dataset into Person C's graph, which is worse
    than omitting it.
    """
    scalars: dict[str, Any] = {}
    inputs: list[dict] = []
    outputs: list[dict] = []

    for key, value in (parameters or {}).items():
        kind = definitions.get(key)
        if kind in INPUT_PARAM_TYPES:
            inputs.append(describe_layer(key, value))
        elif kind in OUTPUT_PARAM_TYPES:
            outputs.append(describe_layer(key, value))
        else:
            scalars[str(key)] = flatten_value(value)

    return scalars, inputs, outputs


def merge_results(outputs: list[dict], results: Any, definitions: dict[str, str]) -> list[dict]:
    """Fill output paths in from the algorithm's return value (§5.6).

    The declared output parameter often holds ``TEMPORARY_OUTPUT`` or a
    placeholder; ``results`` holds what was actually written. Where the two
    disagree, ``results`` wins — it is the observation, the parameter was the
    request.
    """
    if not isinstance(results, dict):
        return outputs

    by_param = {entry["param"]: entry for entry in outputs}
    for key, value in results.items():
        existing = by_param.get(key)
        if existing is None:
            kind = definitions.get(key)
            if kind in INPUT_PARAM_TYPES:
                continue
            described = describe_layer(key, value)
            if kind in OUTPUT_PARAM_TYPES:
                pass  # declared dataset output QGIS reported separately
            elif kind is None and described["path"] is not None:
                pass  # undeclared, but it resolves to a file — take it
            else:
                # A scalar result (a count, an HTML report path we cannot
                # resolve, a boolean). Guessing it is a dataset would put a
                # made-up node into Person C's graph.
                continue
            outputs.append(described)
            by_param[key] = described
            continue
        described = describe_layer(key, value)
        if described["path"] is not None:
            existing["path"] = described["path"]
        for field in MERGEABLE_FIELDS:
            if existing.get(field) is None and described.get(field) is not None:
                existing[field] = described[field]
        if existing["layer_type"] == "unknown" != described["layer_type"]:
            existing["layer_type"] = described["layer_type"]

    return outputs


def build_event(
    *,
    algorithm_id: str,
    session_id: str,
    started_at: str,
    ended_at: str | None,
    agent: dict,
    algorithm_name: str | None = None,
    provider: str | None = None,
    parameters: dict | None = None,
    parameter_definitions: dict[str, str] | None = None,
    results: Any = None,
    status: str = "completed",
    source: str = "post_hook",
    execution_log: str | None = None,
    event_id: str | None = None,
) -> dict:
    """Assemble the frozen event dict (docs/CONTRACT_event.md).

    Pure and QGIS-free: the caller has already pulled ``parameter_definitions``
    off the algorithm. That boundary is what lets the whole capture path — and
    therefore the Review 1 demo — run with no QGIS present.
    """
    definitions = parameter_definitions or {}
    scalars, inputs, outputs = split_parameters(parameters or {}, definitions)
    outputs = merge_results(outputs, results, definitions)

    return {
        "event_id": event_id or str(uuid.uuid4()),
        "session_id": session_id,
        "source": source,
        "algorithm_id": algorithm_id,
        "algorithm_name": algorithm_name,
        "provider": provider or (algorithm_id.split(":")[0] if ":" in algorithm_id else None),
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "parameters": scalars,
        "inputs": inputs,
        "outputs": outputs,
        "agent": agent,
        "execution_log": execution_log,
    }
