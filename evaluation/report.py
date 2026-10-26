"""Every number, table and data figure in the manuscript's §5, from raw results.

    ~/micromamba/envs/gp-q42/bin/python evaluation/report.py   (needs matplotlib)

Reads only files under evaluation/ (and the junit XML of the test runs), and
writes docs/Journal/array/generated/*.tex and docs/Journal/array/figures/
{fig_confusion.png, fig_cost.png, fig_coastal_workflow.dot, fig_hydro_tree.dot}.
No number in those files is typed by hand: each is computed here from a CSV,
JSON, SQLite or XML file named in the code next to it. Running it twice on the
same inputs gives identical text output.
"""

from __future__ import annotations

import collections
import csv
import json
import math
import pathlib
import sqlite3
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PAPER = ROOT / "docs" / "Journal" / "array"
GEN = PAPER / "generated"
FIG = PAPER / "figures"

VERDICTS = ["unchanged", "resaved", "attributes_changed", "geometry_changed",
            "schema_changed", "pixels_changed", "changed", "unknown"]
CHANGE_KINDS = {"attributes_changed", "geometry_changed", "schema_changed", "pixels_changed"}
PRESERVING = {"resave", "row_reorder", "noop"}
FORMATS = ["Shapefile", "GeoPackage", "GeoTIFF"]

macros: dict[str, str] = {}


def macro(name: str, value) -> None:
    assert name.isalpha(), name
    macros[name] = str(value)


def fmt(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}"


def count(n: int) -> str:
    return f"{n:,}"


def load(path: str):
    return json.loads((HERE / path).read_text())


def write(name: str, text: str) -> None:
    (GEN / name).write_text(text.rstrip() + "\n")


def esc(text: str) -> str:
    return text.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")


# ---------------------------------------------------------------------------
# E1 — perturbation suite
# ---------------------------------------------------------------------------

def e1() -> list[dict]:
    rows = list(csv.DictReader((HERE / "perturb_suite/results/trials.csv").open()))
    assert not any(r["error"] for r in rows)
    n = len(rows)
    correct = sum(r["expected"] == r["assigned"] for r in rows)
    macro("EoneTrials", count(n))
    macro("EoneCorrect", count(correct))
    macro("EoneAccuracy", fmt(100 * correct / n))
    per_format = collections.Counter(r["format"] for r in rows)
    for f in FORMATS:
        macro("EoneTrials" + {"Shapefile": "Shp", "GeoPackage": "Gpkg", "GeoTIFF": "Tif"}[f],
              count(per_format[f]))
    macro("EoneSources", count(len({(r["format"], r["source"]) for r in rows})))
    macro("EonePerturbationTypes", count(len({(r["format"], r["perturbation"]) for r in rows})))
    macro("EoneTrialsPerVariant", count(max(int(r["trial"]) for r in rows)))

    expected_classes = [v for v in VERDICTS if any(r["expected"] == v for r in rows)]
    f1s = []
    lines = []
    for v in expected_classes:
        tp = sum(r["expected"] == v and r["assigned"] == v for r in rows)
        fn = sum(r["expected"] == v and r["assigned"] != v for r in rows)
        fp = sum(r["expected"] != v and r["assigned"] == v for r in rows)
        p = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * rec / (p + rec) if p + rec else 0.0)
        cells = [str(sum(r["expected"] == v and r["assigned"] == a for r in rows)) or "0" for a in VERDICTS]
        cells = [c if c != "0" else "." for c in cells]
        lines.append(rf"\verdict{{{esc(v)}}} & " + " & ".join(cells) + rf" & {fmt(100 * rec)} \\")
    precision_row = []
    for a in VERDICTS:
        assigned = [r for r in rows if r["assigned"] == a]
        precision_row.append(fmt(100 * sum(r["expected"] == a for r in assigned) / len(assigned))
                             if assigned else "---")
    lines.append(r"\midrule")
    lines.append(r"Precision (\%) & " + " & ".join(precision_row) + r" & \\")
    write("tab_confusion.tex", "\n".join(lines))
    macro("EoneMacroFone", fmt(100 * sum(f1s) / len(f1s)))
    macro("EoneClasses", count(len(expected_classes)))

    wrong = [r for r in rows if r["expected"] != r["assigned"]]
    kinds = collections.Counter((r["format"], r["perturbation"], r["expected"], r["assigned"]) for r in wrong)
    assert list(kinds) == [("Shapefile", "resave", "resaved", "unchanged")], kinds
    macro("EoneWrong", count(len(wrong)))
    shp_resave = [r for r in rows if r["format"] == "Shapefile" and r["perturbation"] == "resave"]
    macro("EoneShpResaves", count(len(shp_resave)))
    # Changes that were reported as no change, or no-change perturbations reported as change.
    missed = sum(r["perturbation"] not in PRESERVING and r["assigned"] in ("unchanged", "resaved") for r in rows)
    alarms = sum(r["perturbation"] in PRESERVING and r["assigned"] not in ("unchanged", "resaved") for r in rows)
    macro("EoneMissed", count(missed))
    macro("EoneAlarms", count(alarms))
    macro("EoneWritePathsTif", count(len({r["variant"] for r in rows
                                          if r["format"] == "GeoTIFF" and r["perturbation"] == "resave"})))
    dev = list(csv.DictReader((HERE / "perturb_suite/results/dev_run_trials.csv").open()))
    macro("EoneDevTrials", count(len(dev)))
    macro("EoneDevWrong", count(sum(r["expected"] != r["assigned"] for r in dev if not r["error"])))
    return rows


def fig_confusion(rows: list[dict]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    # Sequential blue ramp, steps 100 -> 700 of the reference palette.
    ramp = ["#f7f9fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
    cmap = LinearSegmentedColormap.from_list("seq_blue", ramp)
    short = {"unchanged": "unch.", "resaved": "resaved", "attributes_changed": "attr.",
             "geometry_changed": "geom.", "schema_changed": "schema", "pixels_changed": "pixels",
             "changed": "changed", "unknown": "unknown"}
    vmax = max(collections.Counter((r["format"], r["expected"], r["assigned"]) for r in rows).values())
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), constrained_layout=True)
    for ax, f in zip(axes, FORMATS):
        sub = [r for r in rows if r["format"] == f]
        exp = [v for v in VERDICTS if any(r["expected"] == v for r in sub)]
        cols = [v for v in VERDICTS if any(r["assigned"] == v or r["expected"] == v for r in sub)]
        grid = [[sum(r["expected"] == e and r["assigned"] == a for r in sub) for a in cols] for e in exp]
        ax.imshow(grid, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
        for i, e in enumerate(exp):
            for j, a in enumerate(cols):
                v = grid[i][j]
                if v:
                    ax.text(j, i, str(v), ha="center", va="center", fontsize=11,
                            color="#ffffff" if v > vmax * 0.45 else "#0b0b0b")
        ax.set_xticks(range(len(cols)), [short[c] for c in cols], rotation=35, ha="right", fontsize=10)
        ax.set_yticks(range(len(exp)), [short[e] for e in exp], fontsize=10)
        ax.set_title(f"{f} ({len(sub)} trials)", fontsize=12, color="#0b0b0b")
        ax.set_xlabel("assigned verdict", fontsize=10, color="#52514e")
        ax.tick_params(length=0, colors="#52514e")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([x - 0.5 for x in range(1, len(cols))], minor=True)
        ax.set_yticks([y - 0.5 for y in range(1, len(exp))], minor=True)
        ax.grid(which="minor", color="#ffffff", linewidth=2)
        ax.tick_params(which="minor", length=0)
    axes[0].set_ylabel("expected verdict", fontsize=10, color="#52514e")
    fig.savefig(FIG / "fig_confusion.png", dpi=200, facecolor="#ffffff")
    plt.close(fig)


# ---------------------------------------------------------------------------
# E2 — baselines
# ---------------------------------------------------------------------------

def e2(trials: list[dict]) -> None:
    rows = list(csv.DictReader((HERE / "baselines/results/baselines.csv").open()))
    versions = load("baselines/results/versions.json")
    macro("EtwoKart", esc(versions["kart"].split(",")[0].replace("Kart v", "")))
    macro("EtwoGeodiff", versions["geodiff"])

    def score(column: str | None, kinds: bool) -> dict:
        out = collections.Counter()
        for r in rows:
            value = r["assigned"] if column is None else r[column]
            if value == "n/a":
                continue
            out["trials"] += 1
            if value.startswith("error"):
                out["failed"] += 1
                continue
            preserving = r["perturbation"] in PRESERVING
            said_change = value not in ("unchanged", "resaved")
            if preserving and said_change:
                out["alarms"] += 1
            if not preserving and not said_change:
                out["misses"] += 1
            if not preserving:
                out["change_trials"] += 1
                out["kind_correct"] += value == r["expected"]
        return out

    lines = []
    names = [("B1 whole-file SHA-256", "B1_sha256_file", "all", False),
             ("B2 per-sidecar SHA-256", "B2_sha256_sidecars", "all", False),
             (rf"B3 Kart {macros['EtwoKart']}", "B3_kart", "SHP, GPKG", True),
             (rf"B4 geodiff {macros['EtwoGeodiff']}", "B4_geodiff", "GPKG", True),
             ("GeoProvenance", None, "all", True)]
    for label, column, formats, kinds in names:
        s = score(column, kinds)
        change_trials = sum(1 for r in rows if (column is None or r[column] != "n/a")
                            and r["perturbation"] not in PRESERVING)
        kind = (f"{s['kind_correct']}/{change_trials}" if kinds else "no")
        lines.append(f"{label} & {formats} & {s['trials']} & {s['alarms']} & {s['misses']} & "
                     f"{s['failed']} & {kind} \\\\")
        key = {"B1_sha256_file": "Bone", "B2_sha256_sidecars": "Btwo", "B3_kart": "Bthree",
               "B4_geodiff": "Bfour", None: "Gp"}[column]
        for k in ("trials", "alarms", "misses", "failed", "kind_correct"):
            macro(f"Etwo{key}{k.replace('_', '').title().replace('correct', 'Correct')}", count(s[k]))
        macro(f"Etwo{key}ChangeTrials", count(change_trials))
    write("tab_baselines.tex", "\n".join(lines))

    def per(column, fmt_, pert):
        return sum(1 for r in rows if r["format"] == fmt_ and r["perturbation"] in pert
                   and r[column] not in ("n/a",) and not r[column].startswith("error")
                   and (r[column] == "unchanged") == (pert[0] not in PRESERVING))
    # Specific failures named in the text.
    macro("EtwoBoneShpMissed", count(sum(1 for r in rows if r["format"] == "Shapefile"
                                         and r["perturbation"] not in PRESERVING
                                         and r["B1_sha256_file"] == "unchanged")))
    macro("EtwoBoneShpChangeTrials", count(sum(1 for r in rows if r["format"] == "Shapefile"
                                               and r["perturbation"] not in PRESERVING)))
    kart_wrong = [r for r in rows if r["B3_kart"] not in ("n/a",) and r["perturbation"] in PRESERVING
                  and r["B3_kart"] != "unchanged"]
    macro("EtwoKartResaveAlarms", count(sum(r["perturbation"] == "resave" for r in kart_wrong)))
    macro("EtwoKartReorderAlarms", count(sum(r["perturbation"] == "row_reorder" for r in kart_wrong)))
    geodiff_failed = collections.Counter(r["perturbation"] for r in rows if r["B4_geodiff"].startswith("error"))
    macro("EtwoGeodiffFailedSchema", count(sum(v for k, v in geodiff_failed.items()
                                              if k in ("field_add", "field_drop", "field_retype", "crs_reassign"))))
    macro("EtwoGeodiffSchemaTrials", count(sum(1 for r in rows if r["format"] == "GeoPackage"
                                              and r["perturbation"] in ("field_add", "field_drop",
                                                                         "field_retype", "crs_reassign"))))
    macro("EtwoGeodiffFailedOther", count(sum(v for k, v in geodiff_failed.items()
                                             if k not in ("field_add", "field_drop", "field_retype", "crs_reassign"))))
    macro("EtwoTifResaves", count(sum(1 for r in rows if r["format"] == "GeoTIFF" and r["perturbation"] == "resave")))
    macro("EtwoGpkgResaves", count(sum(1 for r in rows if r["format"] == "GeoPackage" and r["perturbation"] == "resave")))


# ---------------------------------------------------------------------------
# E7 — completeness
# ---------------------------------------------------------------------------

CHANNEL_NAMES = {"run_wrapper": r"\code{processing.run} wrapper", "toolbox": "Toolbox wrapper",
                 "history_signal": "history observer", "batch": "batch wrapper",
                 "post_hook": "post-execution hook"}
PATH_NAMES = {"script": r"Script (\code{processing.run})", "toolbox": "Processing Toolbox",
              "batch": "Batch processing", "modeler": "Graphical Modeler (model steps)"}


def e7() -> None:
    lines = []
    for tag, short in (("4.2.3", "Four"), ("3.34.6", "Three")):
        data = load(f"completeness/results/qgis_{tag}.json")
        caps = {json.loads(c).get("post_execution_hook") for c in data["agent_capabilities"]}
        macro(f"Eseven{short}Hook", "/".join(sorted(c for c in caps if c)))
        total_run = total_rec = 0
        for path in ("script", "toolbox", "batch", "modeler"):
            runs = [r for r in data["runs"] if r["path"] == path]
            run = sum(r["steps"] for r in runs)
            rec = sum(min(r["recorded_steps"], r["steps"]) for r in runs)
            extra = sum(max(0, r["recorded_steps"] - r["steps"]) for r in runs)
            assert extra == 0, (tag, path, "duplicate rows")
            total_run += run
            total_rec += rec
            first = collections.Counter()
            for r in runs:
                first.update(r["first_channel_counts"])
            if path == "modeler":
                models = sum(r["recorded_model_jobs"] for r in runs)
                first_text = ", ".join(f"{CHANNEL_NAMES[c]} ({n})" for c, n in first.most_common())
            else:
                first_text = ", ".join(f"{CHANNEL_NAMES[c]} ({n})" for c, n in first.most_common())
            corro = sum(r["corroborations"] for r in runs)
            errors = sorted({r["error"] for r in runs if r["error"]})
            lines.append(f"{PATH_NAMES[path]} & {tag} & {rec}/{run} & {first_text} & {corro} \\\\")
            key = {"script": "Script", "toolbox": "Toolbox", "batch": "Batch", "modeler": "Modeler"}[path]
            macro(f"Eseven{short}{key}Rec", count(rec))
            macro(f"Eseven{short}{key}Run", count(run))
            macro(f"Eseven{short}{key}Corro", count(corro))
            if path == "modeler":
                macro(f"Eseven{short}ModelJobs", count(models))
            assert not errors, (tag, path, errors)
        macro(f"Eseven{short}Rec", count(total_rec))
        macro(f"Eseven{short}Run", count(total_run))
        lines.append(r"\addlinespace")
    macro("EsevenRepeats", count(max(r["repeat"] for r in data["runs"])))
    macro("EsevenWorkflows", count(len({r["workflow"] for r in data["runs"]})))
    write("tab_completeness.tex", "\n".join(lines[:-1]))


# ---------------------------------------------------------------------------
# E3 — overhead
# ---------------------------------------------------------------------------

WORKFLOW_NAMES = {"coastal_raster": ("Coastal subset", "Coast"),
                  "hydro_raster": ("Hydrology subset", "Hydro"),
                  "dem_full": ("Full DEM", "Dem")}


def e3() -> None:
    lines = []
    for wf, (label, wshort) in WORKFLOW_NAMES.items():
        for tag, short in (("4.2.3", "Four"), ("3.34.6", "Three")):
            data = load(f"overhead/results/overhead_{tag}.json")
            macro("EthreeRuns", count(data["runs_per_condition"]))
            macro(f"Ethree{short}SnapshotKB", fmt(data["registry_snapshot_bytes"] / 1024))
            s = data["summary"][wf]
            jobs = next(r["jobs"] for r in data["runs"] if r["workflow"] == wf)
            off, full = s["off"]["per_job_s"], s["full"]["per_job_s"]

            def ci(d, scale=1000.0, digits=0):
                return f"{fmt(d['mean'] * scale, digits)} $\\pm$ {fmt(d['ci95'] * scale, digits)}"

            added = (full["mean"] - off["mean"]) * 1000
            lines.append(
                f"{label} ({jobs}) & {tag} & {ci(off)} & {ci(full)} & {fmt(added, 0)} & "
                f"{fmt(s['full']['capture_write_ms_per_job']['mean'])} & "
                f"{fmt(s['full']['fingerprint_ms_per_job']['mean'])} & "
                f"{fmt(s['full']['derivation_ms_per_job']['mean'])} & "
                f"{fmt(s['capture']['relative_overhead_pct'])} & {fmt(s['full']['relative_overhead_pct'])} & "
                f"{fmt(s['full']['db_growth_per_job_bytes']['mean'] / 1024)} \\\\")
            k = f"Ethree{short}{wshort}"
            macro(k + "Jobs", count(jobs))
            macro(k + "Off", fmt(off["mean"] * 1000, 0))
            macro(k + "Full", fmt(full["mean"] * 1000, 0))
            macro(k + "AddedMs", fmt(added, 0))
            macro(k + "RelFull", fmt(s["full"]["relative_overhead_pct"]))
            macro(k + "RelCapture", fmt(s["capture"]["relative_overhead_pct"]))
            macro(k + "Write", fmt(s["full"]["capture_write_ms_per_job"]["mean"]))
            macro(k + "Fp", fmt(s["full"]["fingerprint_ms_per_job"]["mean"]))
            macro(k + "Der", fmt(s["full"]["derivation_ms_per_job"]["mean"]))
            macro(k + "DbJob", fmt(s["full"]["db_growth_per_job_bytes"]["mean"] / 1024))
            macro(k + "DbWf", fmt(s["full"]["db_growth_per_workflow_bytes"]["mean"] / 1024))
        lines.append(r"\addlinespace")
    write("tab_overhead.tex", "\n".join(lines[:-1]))


def e3_fingerprint() -> None:
    data = load("overhead/results/fingerprint_bench.json")
    res = data["results"]
    macro("EthreeFpRepeats", count(data["repeats"]))
    macro("EthreeFpBaselineMiB", fmt(data["interpreter_baseline_rss_kb_median"] / 1024))
    sizes = sorted({r["bytes"] for r in res})
    macro("EthreeFpMinMB", fmt(min(r["bytes"] for r in res) / 1e6))
    macro("EthreeFpMaxMB", fmt(max(r["bytes"] for r in res) / 1e6, 0))
    for f, short in (("Shapefile", "Shp"), ("GeoPackage", "Gpkg"), ("GeoTIFF", "Tif")):
        largest = max((r for r in res if r["format"] == f), key=lambda r: r["bytes"])
        macro(f"EthreeFp{short}LargestMB", fmt(largest["bytes"] / 1e6, 0))
        macro(f"EthreeFp{short}LargestS", fmt(largest["seconds_median"]))
        macro(f"EthreeFp{short}LargestMiB", fmt(largest["peak_rss_kb_median"] / 1024, 0))
        rates = [r["bytes"] / 1e6 / r["seconds_median"] for r in res
                 if r["format"] == f and r["bytes"] > 50e6]
        lo, hi = fmt(min(rates), 0), fmt(max(rates), 0)
        macro(f"EthreeFp{short}MBps", lo if lo == hi else f"{lo}--{hi}")
        macro(f"EthreeFp{short}MaxMiB", fmt(max(r["peak_rss_kb_median"] for r in res if r["format"] == f) / 1024, 0))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    series = {"Shapefile": ("#2a78d6", "o"), "GeoPackage": ("#eb6834", "s"), "GeoTIFF": ("#1baf7a", "^")}
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.4), constrained_layout=True)
    for f, (colour, marker) in series.items():
        pts = sorted((r for r in res if r["format"] == f), key=lambda r: r["bytes"])
        xs = [r["bytes"] / 1e6 for r in pts]
        left.plot(xs, [r["seconds_median"] for r in pts], color=colour, marker=marker,
                  markersize=8, linewidth=2, label=f, markeredgecolor="#ffffff", markeredgewidth=1.5)
        right.plot(xs, [r["peak_rss_kb_median"] / 1024 for r in pts], color=colour, marker=marker,
                   markersize=8, linewidth=2, label=f, markeredgecolor="#ffffff", markeredgewidth=1.5)
        left.annotate(f, (xs[-1], pts[-1]["seconds_median"]), xytext=(6, 0),
                      textcoords="offset points", va="center", fontsize=10, color="#0b0b0b")
        nudge = {"Shapefile": -7, "GeoPackage": 7}.get(f, 0)  # their memory lines nearly coincide
        right.annotate(f, (xs[-1], pts[-1]["peak_rss_kb_median"] / 1024), xytext=(6, nudge),
                       textcoords="offset points", va="center", fontsize=10, color="#0b0b0b")
    baseline = data["interpreter_baseline_rss_kb_median"] / 1024
    right.axhline(baseline, color="#52514e", linewidth=1, linestyle=(0, (1, 2)))
    right.text(1.0, baseline - 1.5, "interpreter alone", va="top", fontsize=9, color="#52514e")
    for ax, ylabel in ((left, "fingerprinting time (s)"), (right, "peak resident memory (MiB)")):
        ax.set_xscale("log")
        if ax is left:
            ax.set_yscale("log")
        else:
            ax.set_ylim(0, max(r["peak_rss_kb_median"] for r in res) / 1024 * 1.15)
        ax.axvline(500, color="#52514e", linewidth=1, linestyle=(0, (4, 3)))
        low = ax.get_ylim()[0] * (1.6 if ax is left else 1) + (0 if ax is left else 3)
        ax.text(480, low, "500 MB: whole-file\ndigest replaced ", ha="right", va="bottom",
                fontsize=9, color="#52514e")
        ax.set_xlabel("dataset size (MB)", fontsize=10, color="#52514e")
        ax.set_ylabel(ylabel, fontsize=10, color="#52514e")
        ax.grid(True, which="major", color="#e6e5e1", linewidth=0.8)
        ax.tick_params(colors="#52514e", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c3c2b7")
        ax.set_xlim(right=ax.get_xlim()[1] * 4)
    left.legend(frameon=False, fontsize=10, loc="upper left")
    fig.savefig(FIG / "fig_cost.png", dpi=200, facecolor="#ffffff")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Case study 1
# ---------------------------------------------------------------------------

def case1() -> None:
    base = load("case_cuddalore/results/baseline.json")
    pert = load("case_cuddalore/results/perturbations.json")
    scenes = load("case_cuddalore/data/scenes.json")["scenes"]
    rec = base["record"]
    macro("CoastJobs", count(rec["jobs"]))
    macro("CoastFiles", count(rec["files"]))
    macro("CoastRelations", count(sum(rec["relations"].values())))
    macro("CoastDerivations", count(rec["relations"]["wasDerivedFrom"]))
    macro("CoastUsed", count(rec["relations"]["used"]))
    macro("CoastGenerated", count(rec["relations"]["wasGeneratedBy"]))
    macro("CoastAttributed", count(rec["relations"]["wasAttributedTo"]))
    macro("CoastFingerprints", count(rec["fingerprints"]))
    macro("CoastDbKB", fmt(rec["db_bytes"] / 1024, 0))
    macro("CoastRegistryAlgorithms", count(rec["registry_snapshot_algorithms"][0]))
    assert set(rec["channels"]) == {"run_wrapper"}
    macro("CoastTransects", count(base["transects"]))
    macro("CoastYears", fmt(base["years"]))
    macro("CoastEprMean", fmt(base["epr_mean"], 2))
    macro("CoastEprMin", fmt(base["epr_min"], 2))
    macro("CoastEprMax", fmt(base["epr_max"], 2))
    for key in ("baseline", "recent", "alt1", "alt2", "alt3"):
        if key in scenes:
            macro("Scene" + key.title().replace("1", "One").replace("2", "Two").replace("3", "Three"),
                  rf"\nolinkurl{{{scenes[key]['product_id']}}}")  # breakable: ids are 40 chars
            macro("Cloud" + key.title().replace("1", "One").replace("2", "Two").replace("3", "Three"),
                  fmt(scenes[key]["cloud_cover"], 2))

    by = collections.defaultdict(list)
    for t in pert["trials"]:
        by[t["id"]].append(t)
    expected = pert["expected"]
    labels = {
        "P1": "silent re-save of the 2026 shoreline GeoPackage (two \\code{ogr2ogr} option sets, QGIS ``Save As'')",
        "P2": "MNDWI threshold $t$ from 0.0 to 0.02, 2026 chain re-run in QGIS",
        "P3": "2026 scene replaced by another acquisition (three scenes)",
        "P4": "attribute edit, \\code{source\\_scene} on one shoreline feature",
        "P5": "control, no change",
    }
    lines = []
    for pid in ("P1", "P2", "P3", "P4", "P5"):
        trials = by[pid]
        hits = sum(t["verdict"] == expected[pid] for t in trials)
        verdicts = collections.Counter(t["verdict"] for t in trials)
        verdict_text = ", ".join(rf"\verdict{{{esc(v)}}}" for v in verdicts)
        effects = [t["effect"] for t in trials]
        if all(e["identical"] for e in effects):
            effect = f"none: all {effects[0]['transects_compared']} rates identical"
        else:
            parts = []
            for e in effects:
                parts.append(f"{fmt(e['class_changed_pct'])}\\% of {e['transects_compared']} transects change class")
            if len(parts) == 1:
                e = effects[0]
                effect = (f"mean EPR {'+' if e['mean_delta_epr'] >= 0 else '$-$'}"
                          f"{fmt(abs(e['mean_delta_epr']), 3)} m/yr; {e['class_changed']} of "
                          f"{e['transects_compared']} transects ({fmt(e['class_changed_pct'])}\\%) change class")
            else:
                effect = (f"{min(e['transects_compared'] for e in effects)}--{max(e['transects_compared'] for e in effects)} "
                          f"transects comparable; {fmt(min(e['class_changed_pct'] for e in effects), 0)}--"
                          f"{fmt(max(e['class_changed_pct'] for e in effects), 0)}\\% change class")
        lines.append(f"{pid} & {labels[pid]} ($\\times${len(trials)}) & {verdict_text} "
                     f"({hits}/{len(trials)} = hypothesis) & {effect} \\\\")
        macro(f"Coast{pid.replace('P', 'P').replace('1', 'one').replace('2', 'two').replace('3', 'three').replace('4', 'four').replace('5', 'five')}Hits",
              f"{hits}/{len(trials)}")
    write("tab_coastal.tex", "\n".join(lines))
    p2 = by["P2"][0]["effect"]
    macro("CoastPtwoDeltaEpr", fmt(p2["mean_delta_epr"], 3))
    macro("CoastPtwoAbsDeltaEpr", fmt(p2["mean_abs_delta_epr"], 3))
    macro("CoastPtwoClassChanged", count(p2["class_changed"]))
    macro("CoastPtwoClassChangedPct", fmt(p2["class_changed_pct"]))
    macro("CoastPtwoMoved", ", ".join(esc(m) for m in by["P2"][0]["moved"] if m != "file"))
    macro("CoastPtwoHeld", ", ".join(esc(m) for m in by["P2"][0]["held"]))
    macro("CoastPthreeTrials", count(len(by["P3"])))
    macro("CoastPerturbationTrials", count(len(pert["trials"])))
    macro("CoastPerturbationHits", count(sum(t["verdict"] == expected[t["id"]] for t in pert["trials"])))

    # Fig. 7: the recorded job sequence of the baseline workflow, collapsed into
    # its three repeated chains.
    with sqlite3.connect(HERE / "case_cuddalore/provenance.db") as conn:
        wf = conn.execute("SELECT w.id FROM workflows w JOIN workflow_activities wa ON wa.workflow_id = w.id "
                          "GROUP BY w.id HAVING count(*) = ?", (rec["jobs"],)).fetchone()[0]
        algs = [a for (a,) in conn.execute(
            "SELECT a.algorithm_id FROM activities a JOIN workflow_activities wa ON wa.activity_id = a.id "
            "WHERE wa.workflow_id = ? ORDER BY wa.sequence_order", (wf,))]
    _coastal_dot(algs)


def _runs(algs: list[str]) -> list[tuple[str, int]]:
    out: list[list] = []
    for a in algs:
        if out and out[-1][0] == a:
            out[-1][1] += 1
        else:
            out.append([a, 1])
    return [(a, n) for a, n in out]


_DOT_HEAD = ['  graph [rankdir=TB, compound=true, nodesep=0.3, ranksep=0.14, fontname="Liberation Sans", fontsize=10, bgcolor=white, pad=0.15];',
             '  node [fontname="Liberation Sans", fontsize=10, shape=box, style=filled, fillcolor="#eeeeee", color="#888888", margin="0.08,0.03", height=0.25];',
             '  edge [fontname="Liberation Sans", fontsize=9, color="#555555", arrowsize=0.5];']


def _dot_label(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _coastal_dot(algs: list[str]) -> None:
    # The chain per date starts at a raster clip and ends at the shoreline clip.
    starts = [i for i, a in enumerate(algs) if a == "gdal:cliprasterbyextent"
              and (i == 0 or algs[i - 1] != "gdal:cliprasterbyextent")]
    assert len(starts) == 2, starts
    per_date_len = algs.index("native:clip", starts[0]) - starts[0] + 1
    pre = algs[:starts[0]]
    date1 = algs[starts[0]:starts[0] + per_date_len]
    date2 = algs[starts[1]:starts[1] + per_date_len]
    assert date1 == date2
    rates = algs[starts[1] + per_date_len:]
    assert len(pre) + 2 * per_date_len + len(rates) == len(algs)
    notes = {("date", "gdal:rastercalculator"): "MNDWI, then threshold t ◀ P2",
             ("date", "gdal:cliprasterbyextent"): "green + SWIR1 bands ◀ P3",
             ("date", "native:clip"): "= shoreline per date ◀ P1, P4, P5"}
    # Two columns, so the figure stays legible at page width: the area of
    # interest above the per-date chain, and the rate computation beside them.
    lines = ["digraph coastal {"] + _DOT_HEAD

    def chain(prefix: str, title: str, items: list[str], scope: str):
        out = [f"  subgraph cluster_{prefix} {{",
               f'    label=<<B>{_dot_label(title)}</B>>; labeljust=l; style=filled; fillcolor="#fafafa"; color="#aaaaaa";']
        names = []
        for i, (a, n) in enumerate(_runs(items)):
            label = _dot_label(a.removeprefix("native:") + (f" ×{n}" if n > 1 else ""))
            note = notes.get((scope, a))
            if note:
                label += f'<BR/><I><FONT POINT-SIZE="9">{_dot_label(note)}</FONT></I>'
            out.append(f"    {prefix}{i} [label=<{label}>];")
            names.append(f"{prefix}{i}")
        out += [f"    {a} -> {b};" for a, b in zip(names, names[1:])]
        out.append("  }")
        return out, names[0], names[-1]

    p, p_first, p_last = chain("A", f"Area of interest ({len(pre)} jobs)", pre, "pre")
    d, d_first, d_last = chain("D", f"Per date, run for 2015 and for 2026 ({per_date_len} jobs each)", date1, "date")
    r, r_first, r_last = chain("R", f"Rates ({len(rates)} jobs)", rates, "rates")
    lines += p + d + r
    # Arrows between columns end at the cluster borders, not on a node.
    lines += [f"  {p_last} -> {d_first} [ltail=cluster_A, lhead=cluster_D];",
              f"  {d_last} -> {r_first} [ltail=cluster_D, lhead=cluster_R, constraint=false];",
              '  OUT [label="End Point Rate\\nper transect, classified", style="rounded,bold", fillcolor=white, color=black];',
              f"  {r_last} -> OUT;",
              "}"]
    (FIG / "fig_coastal_workflow.dot").write_text("\n".join(lines) + "\n")
    macro("CoastPerDateJobs", count(per_date_len))
    macro("CoastPreJobs", count(len(pre)))
    macro("CoastRatesJobs", count(len(rates)))


# ---------------------------------------------------------------------------
# Case study 2
# ---------------------------------------------------------------------------

def case2() -> None:
    h = load("case_hydro/results/hydro.json")
    rec = h["record_after_all_runs"]
    expected = json.loads((HERE / "case_hydro/expected.json").read_text())
    base = h["baseline"]
    macro("HydroWatershedKm", fmt(base["watershed_km2"], 0))
    macro("HydroStreamSegments", count(base["stream_segments"]))
    macro("HydroStreamKm", fmt(base["stream_km"], 0))
    macro("HydroThreshold", count(h["stream_threshold"]))
    macro("HydroDemItem", rf"\nolinkurl{{{h['source']['item']}}}")
    macro("HydroCollection", esc(h["source"]["collection"]))
    w = h["source"]["window_lonlat"]
    macro("HydroWindow", f"{w[0]}--{w[2]}\\,\\textdegree{{}}E, {w[1]}--{w[3]}\\,\\textdegree{{}}N")
    with sqlite3.connect(HERE / "case_hydro/provenance.db") as conn:
        wfs = conn.execute("SELECT workflow_id, count(*) FROM workflow_activities GROUP BY workflow_id").fetchall()
        # The baseline run is the first job of the session and the chain that follows it.
        first = conn.execute("SELECT id FROM activities ORDER BY started_at LIMIT 1").fetchone()[0]
        wf = conn.execute("SELECT workflow_id FROM workflow_activities WHERE activity_id = ?", (first,)).fetchone()[0]
        acts = conn.execute("SELECT a.id, a.algorithm_id FROM activities a JOIN workflow_activities wa "
                            "ON wa.activity_id = a.id WHERE wa.workflow_id = ? ORDER BY wa.sequence_order",
                            (wf,)).fetchall()
        n_base = len(acts) // 2 if len(acts) == 2 * min(c for _, c in wfs) else len(acts)
        base_acts = acts[:n_base]
        ids = {a for a, _ in base_acts}
        rels = conn.execute("SELECT relation_type, source_id, target_id FROM relations "
                            "WHERE relation_type IN ('used', 'wasGeneratedBy', 'wasDerivedFrom')").fetchall()
        entities = dict(conn.execute("SELECT id, file_path FROM entities").fetchall())
    used = [(s, t) for typ, s, t in rels if typ == "used" and s in ids]
    gen = [(s, t) for typ, s, t in rels if typ == "wasGeneratedBy" and t in ids]
    files = sorted({t for _, t in used} | {s for s, _ in gen})
    derived = [(s, t) for typ, s, t in rels if typ == "wasDerivedFrom" and s in files and t in files]
    macro("HydroJobs", count(len(base_acts)))
    macro("HydroFiles", count(len(files)))
    macro("HydroDerivations", count(len(derived)))
    macro("HydroAllJobs", count(rec["jobs"]))
    macro("HydroAllFiles", count(rec["files"]))
    assert set(rec["channels"]) == {"run_wrapper"}
    macro("HydroAlgorithms", ", ".join(rf"\code{{{esc(a)}}}" for a in dict.fromkeys(a for _, a in base_acts)))
    _hydro_dot(base_acts, used, gen, entities)

    labels = {"H1": "DEM re-saved with Deflate compression and tiling",
              "H2": "DEM raised by 5\\,m on a 33 $\\times$ 33-cell block",
              "H3": "stream threshold 2,000 $\\rightarrow$ 1,000 cells (stream network)",
              "H4": "CRS of the watershed polygon reassigned"}
    lines = [f"--- & capture of the baseline run & {len(base_acts)} jobs, {len(files)} files, "
             f"{len(derived)} derivations & --- \\\\"]
    for t in h["trials"]:
        e = t["effect"]
        if e is None:
            effect = "not re-run (a label change)"
        else:
            parts = []
            if fmt(e["watershed_km2"], 1) == fmt(base["watershed_km2"], 1):
                parts.append("watershed area unchanged")
            else:
                parts.append(f"watershed {fmt(e['watershed_km2'], 0)} km$^2$")
            if e["stream_segments"] != base["stream_segments"]:
                parts.append(f"{count(e['stream_segments'])} stream segments (from {count(base['stream_segments'])})")
            dk = e["stream_km"] - base["stream_km"]
            parts.append("stream length identical" if abs(dk) < 1e-6 else
                         f"stream length {'+' if dk > 0 else '$-$'}{fmt(abs(dk), 2 if abs(dk) < 10 else 0)} km")
            effect = "; ".join(parts)
        ok = "=" if t["verdict"] == expected[t["id"]] else "$\\neq$"
        lines.append(f"{t['id']} & {labels[t['id']]} & \\verdict{{{esc(t['verdict'])}}} ({ok} "
                     f"\\verdict{{{esc(expected[t['id']])}}}) & {effect} \\\\")
        macro(f"Hydro{t['id'].replace('H', 'H').replace('1', 'one').replace('2', 'two').replace('3', 'three').replace('4', 'four')}Verdict",
              rf"\verdict{{{esc(t['verdict'])}}}")
    write("tab_hydro.tex", "\n".join(lines))
    h2 = next(t for t in h["trials"] if t["id"] == "H2")["effect"]
    macro("HydroHtwoStreamDeltaKm", fmt(base["stream_km"] - h2["stream_km"], 2))
    h3 = next(t for t in h["trials"] if t["id"] == "H3")
    macro("HydroHthreeSegments", count(h3["effect"]["stream_segments"]))
    macro("HydroHthreeMoved", ", ".join(esc(m) for m in h3["moved"] if m != "file"))
    macro("HydroHits", count(sum(t["verdict"] == expected[t["id"]] for t in h["trials"])))
    macro("HydroTrials", count(len(h["trials"])))


def _hydro_dot(acts, used, gen, entities) -> None:
    """Files as boxes; each job is the labelled edge from what it read to what it wrote."""
    marks = {"dem_window.tif": "◀ H1, H2", "streams.gpkg": "◀ H3", "watershed.gpkg": "◀ H4"}
    lines = ["digraph hydro {"] + _DOT_HEAD
    files = sorted({t for _, t in used} | {s for s, _ in gen}, key=lambda f: entities[f] or "")
    names = {f: f"F{i}" for i, f in enumerate(files)}
    for f in files:
        base = pathlib.PurePath(entities[f] or "memory").name
        mark = marks.get(base)
        label = _dot_label(base) + (f"<BR/><B>{_dot_label(mark)}</B>" if mark else "")
        lines.append(f"  {names[f]} [label=<{label}>];")
    for aid, alg in acts:
        for f_in in [f for a, f in used if a == aid]:
            for f_out in [f for f, a in gen if a == aid]:
                lines.append(f'  {names[f_in]} -> {names[f_out]} [label=" {alg}"];')
    lines.append("}")
    (FIG / "fig_hydro_tree.dot").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# E6 — audit
# ---------------------------------------------------------------------------

def e6() -> None:
    a = load("audit/results/scenarios.json")
    order = [
        ("coastal_unchanged_offline", "Coastal workflow, unchanged, audited offline from the database"),
        ("coastal_after_P1", "Coastal workflow after P1 (re-save of the 2026 shoreline)"),
        ("coastal_after_P2", "Coastal workflow after P2 (re-thresholded 2026 shoreline)"),
        ("coastal_after_P3", "Coastal workflow after P3 (2026 scene replaced, both bands)"),
        ("coastal_audited_on_qgis_3_34", "Coastal workflow (QGIS 4.2.3) audited on QGIS 3.34.6"),
        ("hydro_unchanged_offline", "Hydrology workflow (baseline and H3 runs), unchanged, audited offline"),
        ("hydro_after_H2", "Hydrology workflow after H2 (DEM edit)"),
    ]
    names = {"input_exists": "exists", "input_unchanged": "unchanged", "algorithm_available": "available",
             "environment_similar": "environment", "parameters_valid": "parameters"}
    lines = []
    for key, label in order:
        s = a[key]
        failing = [f"{names[n]} {fmt(v)}" for n, v in s["components"].items() if v is not None and v < 100]
        excluded = ", ".join(names[n] for n in s["excluded"]) or "none"
        lines.append(f"{label} & {fmt(s['score'])} & {s['band']} & {excluded} & "
                     f"{'; '.join(failing) or '---'} \\\\")
        k = "Audit" + "".join(p.title() for p in key.replace("3_34", "three").split("_")).replace("P1", "Pone") \
            .replace("P2", "Ptwo").replace("P3", "Pthree").replace("H2", "Htwo")
        k = "".join(ch for ch in k if ch.isalpha())
        macro(k, fmt(s["score"]))
    write("tab_audit.tex", "\n".join(lines))
    q = a["coastal_audited_on_qgis_3_34"]["audit_host"]
    macro("AuditHostGdal", q["gdal_version"])
    macro("AuditHostPython", q["python_version"])
    macro("AuditOfflinePython", a["_audit_host"]["python"])
    macro("AuditHydroJobs", count(a["hydro_unchanged_offline"]["steps"]))
    p2 = a["coastal_after_P2"]["components"]["input_unchanged"]
    macro("AuditPtwoUnchanged", fmt(p2))
    panel = load("figures/results/panel.json")
    macro("PanelScore", fmt(panel["score"], 0))
    macro("PanelBand", panel["band"])
    macro("PanelExcluded", ", ".join(names[n] for n in panel["excluded"]) or "none")
    macro("PanelQgis", panel["versions"]["qgis_version"])
    lines.insert(0, f"Live two-job chain, inputs moved (\\cref{{fig:panel}}) & {fmt(panel['score'])} & "
                    f"{panel['band']} & {macros['PanelExcluded']} & "
                    + "; ".join(f"{names[n]} {fmt(v)}" for n, v in panel["components"].items()
                                if v is not None and v < 100) + r" \\")
    write("tab_audit.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# E8 — environment and tests
# ---------------------------------------------------------------------------

def e8() -> None:
    for tag, short in (("4.2.3", "Four"), ("3.34.6", "Three")):
        v = load(f"completeness/results/qgis_{tag}.json")["versions"]
        macro(f"Qgis{short}", v["qgis_version"])
        macro(f"Qgis{short}Gdal", v["gdal_version"])
        macro(f"Qgis{short}Proj", v["proj_version"])
        macro(f"Qgis{short}Geos", v["geos_version"])
        macro(f"Qgis{short}Python", v["python_version"])
        macro(f"Qgis{short}Qt", v.get("qt_version", "unknown"))
    env = load("perturb_suite/results/environment.json") if (HERE / "perturb_suite/results/environment.json").exists() else {}
    for name, short in (("tests_noqgis.xml", "Unit"), ("tests_q42.xml", "QgisFour"), ("tests_q334.xml", "QgisThree")):
        root = ET.parse(HERE / name).getroot()
        suite = root if root.tag == "testsuite" else root[0]
        assert suite.get("failures") == "0" and suite.get("errors") == "0", name
        macro(f"Tests{short}", count(int(suite.get("tests")) - int(suite.get("skipped") or 0)))
    hw = json.loads((HERE / "ENVIRONMENT.json").read_text())
    macro("HwCpu", esc(hw["cpu"]))
    macro("HwThreads", hw["threads"])
    macro("HwRamGiB", hw["ram_gib"])
    macro("HwOs", esc(hw["os"]))


def main() -> None:
    GEN.mkdir(exist_ok=True)
    rows = e1()
    fig_confusion(rows)
    e2(rows)
    e7()
    e3()
    e3_fingerprint()
    case1()
    case2()
    e6()
    e8()
    text = ["% Generated by evaluation/report.py — do not edit."]
    text += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
    write("numbers.tex", "\n".join(text))
    print(f"{len(macros)} numbers, tables and figures written to {GEN.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
