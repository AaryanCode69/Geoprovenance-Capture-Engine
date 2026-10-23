"""E2 — baselines on the E1 trials (manuscript §5.3, Table 8).

    evaluation/qgis.sh gp-q42 evaluation/baselines/run_baselines.py

Reads evaluation/perturb_suite/results/trials.csv and the perturbed copies it
names, and runs four baselines against each trial's source:

    B1  SHA-256 of the file the record points at (for a Shapefile, the .shp)
    B2  SHA-256 over every file of the dataset (.shp, .shx, .dbf, .prj, .cpg)
    B3  Kart 0.17.1 — import the source, commit; import the copy over it;
        `kart diff -o json` between the two commits; reset
    B4  geodiff 2.3.2 (pygeodiff) — changeset between the two GeoPackages

B1/B2 answer changed/unchanged only. For B3/B4 the diff is read for a kind of
change, mapped onto the nearest verdict: a schema or CRS change ->
schema_changed; inserted or deleted features, or a changed geometry ->
geometry_changed; only non-geometry values changed -> attributes_changed; no
diff -> unchanged. Writes results/baselines.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIALS = ROOT / "evaluation" / "perturb_suite" / "results" / "trials.csv"
KART = os.environ.get("KART", str(pathlib.Path.home() / ".local/opt/Kart-0.17.1-linux-x86_64/kart/kart"))


def sidecars(path: pathlib.Path) -> list[pathlib.Path]:
    if path.suffix.lower() != ".shp":
        return [path]
    return [p for p in (path.with_suffix(s) for s in (".shp", ".shx", ".dbf", ".prj", ".cpg"))
            if p.exists()]


def sha(paths: list[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for p in paths:
        digest.update(p.suffix.encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Kart
# ---------------------------------------------------------------------------

def _kart(args: list[str], cwd: pathlib.Path) -> str:
    result = subprocess.run([KART, *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-400:])
    return result.stdout


def _prefix(path: pathlib.Path) -> str:
    return ("OGR:" if path.suffix.lower() == ".shp" else "GPKG:") + str(path)


class KartRepo:
    def __init__(self, source: pathlib.Path, workdir: pathlib.Path):
        self.dir = workdir / "repo"
        _kart(["init", str(self.dir), "--import", _prefix(source)], workdir)
        self.base = _kart(["git", "rev-parse", "HEAD"], self.dir).strip()

    def classify(self, copy: pathlib.Path, dataset: str) -> str:
        try:
            try:
                _kart(["import", _prefix(copy), "--replace-existing", "--dataset", dataset], self.dir)
            except RuntimeError as exc:
                if "No changes to commit" in str(exc):
                    return "unchanged"  # Kart found the import identical to the commit
                raise
            diff = json.loads(_kart(["diff", self.base, "HEAD", "-o", "json"], self.dir) or "{}")
        finally:
            _kart(["reset", self.base, "--discard-changes"], self.dir)
        return _kind_from_kart(diff)


def _kind_from_kart(diff: dict) -> str:
    body = next(iter(diff.values()), {}) if diff else {}
    if not body:
        return "unchanged"
    meta_changed = feature_changes = False
    geometry = attributes = False
    for dataset in body.values():
        meta = dataset.get("meta") or {}
        if any(k == "schema.json" or k.startswith("crs") for k in meta):
            meta_changed = True
        for change in dataset.get("feature") or []:
            feature_changes = True
            old, new = change.get("-"), change.get("+")
            if old is None or new is None:
                geometry = True
                continue
            geom_keys = {k for k in set(old) | set(new) if k.lower() in ("geom", "geometry", "_ogr_geometry_")}
            if any(old.get(k) != new.get(k) for k in geom_keys):
                geometry = True
            if any(old.get(k) != new.get(k) for k in set(old) | set(new) if k not in geom_keys):
                attributes = True
    if meta_changed:
        return "schema_changed"
    if geometry:
        return "geometry_changed"
    if attributes:
        return "attributes_changed"
    return "changed" if feature_changes else "unchanged"


# ---------------------------------------------------------------------------
# geodiff
# ---------------------------------------------------------------------------

def geodiff_classify(source: pathlib.Path, copy: pathlib.Path, workdir: pathlib.Path) -> str:
    import pygeodiff

    gd = pygeodiff.GeoDiff()
    changeset = workdir / "changes.bin"
    listing = workdir / "changes.json"
    schema_json = workdir / "schema.json"
    try:
        gd.create_changeset(str(source), str(copy), str(changeset))
    except pygeodiff.GeoDiffLibError as exc:
        return f"error: {exc}".split("\n")[0][:120]
    gd.list_changes(str(changeset), str(listing))
    changes = json.loads(listing.read_text()).get("geodiff", [])
    if not changes:
        return "unchanged"
    gd.schema("sqlite", "", str(source), str(schema_json))
    geometry_columns = {
        table["table"]: {i for i, c in enumerate(table["columns"]) if c.get("type") == "geometry"}
        for table in json.loads(schema_json.read_text()).get("geodiff_schema", [])
    }
    geometry = attributes = False
    for change in changes:
        if change["type"] in ("insert", "delete"):
            geometry = True
            continue
        geoms = geometry_columns.get(change["table"], set())
        for column in change.get("changes", []):
            if "old" in column or "new" in column:
                if column["column"] in geoms:
                    geometry = True
                else:
                    attributes = True
    if geometry:
        return "geometry_changed"
    return "attributes_changed" if attributes else "changed"


def main() -> int:
    rows = list(csv.DictReader(TRIALS.open()))
    out = []
    repos: dict[str, KartRepo] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for i, row in enumerate(rows):
            source = ROOT / row["source_path"]
            copy = ROOT / row["copy"]
            if row["error"] or not copy.exists():
                continue
            b1 = "changed" if sha([source]) != sha([copy]) else "unchanged"
            b2 = "changed" if sha(sidecars(source)) != sha(sidecars(copy)) else "unchanged"
            b3 = b4 = "n/a"
            if row["format"] in ("Shapefile", "GeoPackage"):
                key = row["source_path"]
                if key not in repos:
                    work = tmp / f"kart{len(repos)}"
                    work.mkdir()
                    repos[key] = KartRepo(source, work)
                dataset = source.stem if row["format"] == "Shapefile" else None
                if dataset is None:
                    import sqlite3

                    with sqlite3.connect(source) as conn:
                        dataset = conn.execute(
                            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
                        ).fetchone()[0]
                try:
                    b3 = repos[key].classify(copy, dataset)
                except RuntimeError as exc:
                    b3 = f"error: {exc}".split("\n")[0][:120]
            if row["format"] == "GeoPackage":
                work = tmp / f"geodiff{i}"
                work.mkdir()
                b4 = geodiff_classify(source, copy, work)
            out.append({**{k: row[k] for k in ("format", "source", "perturbation", "variant",
                                               "trial", "expected", "assigned")},
                        "B1_sha256_file": b1, "B2_sha256_sidecars": b2,
                        "B3_kart": b3, "B4_geodiff": b4})
            print(f"{row['format']:10} s{row['source']} {row['perturbation']:15} "
                  f"B1={b1:9} B2={b2:9} B3={b3:20} B4={b4}")
    (HERE / "results").mkdir(exist_ok=True)
    with (HERE / "results" / "baselines.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    versions = {"kart": _kart(["--version"], ROOT).splitlines()[0]}
    import pygeodiff

    versions["geodiff"] = pygeodiff.GeoDiff().version()
    (HERE / "results" / "versions.json").write_text(json.dumps(versions, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
