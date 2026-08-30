"""Reproducibility audit — the 5-component weighted score.

Owner: Person C (README "Person C — Visualization & Reproducibility Audit").
Written by Person A under the explicit written override of RULES.md §1.2 [HARD]
requested on 30 Aug 2026, so that the workflow panel could be demonstrated.
Person C owns this file; A owns nothing in it.

    THIS MODULE IMPORTS NO QGIS at module level. The two checks that genuinely
    need a live Processing registry reach for it lazily and report "not checked"
    when it is absent, so the whole scorer runs in `make test` and in a demo on
    a machine with no QGIS (RULES.md §7.3).

The weights are research doc §4.3 Layer 5, unchanged:

    input data exists       30%   the file is still where the record says
    input data unchanged    25%   and its contents still match
    algorithm available     20%   QGIS still has the tool that made it
    environment similar     15%   on a close enough version of QGIS
    parameters valid        10%   with settings the tool still accepts

Two decisions the research doc leaves open, made here
    Score bands. §4.3's example prints "87/100 (HIGH)" and never says what HIGH
    means. Taken as HIGH >= 85, MODERATE >= 60, LOW below. A judgement, not a
    finding — say so if it is quoted.

    A check that could not be run scores NULL, never 100. Outside QGIS there is
    no Processing registry, so "algorithm available" and "parameters valid" are
    unanswerable, and the overall score is the weighted mean over the checks
    that DID run. Scoring an unrun check as a pass would make every offline
    audit report perfect reproducibility, which is the same
    unmeasured-equals-fine mistake `fingerprint/compare.py` refuses, and the
    same one that let three §5.9 tests pass against a broken dedup in A6.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from . import prov
from .capture import environment
from .fingerprint import compare, hash as hashing

#: research doc §4.3 Layer 5. These sum to 100 and are not ours to retune.
WEIGHTS: dict[str, int] = {
    "input_exists": 30,
    "input_unchanged": 25,
    "algorithm_available": 20,
    "environment_similar": 15,
    "parameters_valid": 10,
}

#: Ordered for the report, with the wording §4.3's example uses.
COMPONENT_LABELS = (
    ("input_exists", "Input data exists"),
    ("input_unchanged", "Input data unchanged"),
    ("algorithm_available", "Algorithms available"),
    ("environment_similar", "Environment similar"),
    ("parameters_valid", "Parameters valid"),
)

HIGH, MODERATE, LOW = "HIGH", "MODERATE", "LOW"


def band(score: float) -> str:
    """The qualitative label beside the number. See the module docstring."""
    if score >= 85:
        return HIGH
    if score >= 60:
        return MODERATE
    return LOW


@dataclass(frozen=True)
class StepFinding:
    """One job's five verdicts. ``None`` means the check could not be run."""

    activity_id: str
    label: str
    checks: dict[str, bool | None]
    notes: dict[str, str]

    def failed(self) -> list[str]:
        return [name for name, ok in self.checks.items() if ok is False]


@dataclass(frozen=True)
class AuditResult:
    workflow_id: str
    workflow_name: str
    steps: list[StepFinding]
    components: dict[str, float | None]
    overall: float
    #: entity id -> one of MISSING / CHANGED / VERIFIED / UNKNOWN. What colours
    #: a node in the panel (research doc §4.3 Layer 4).
    file_status: dict[str, str]

    @property
    def band(self) -> str:
        return band(self.overall)

    def tally(self, component: str) -> tuple[int, int]:
        """(steps that passed, steps where the check could run)."""
        ran = [s for s in self.steps if s.checks[component] is not None]
        return sum(1 for s in ran if s.checks[component]), len(ran)

    def reasons(self, component: str) -> list[str]:
        """Why this component is not 100, in the order the steps ran."""
        return [
            s.notes[component]
            for s in self.steps
            if s.checks[component] is False and component in s.notes
        ]


# ---------------------------------------------------------------------------
# The five checks
# ---------------------------------------------------------------------------


#: What one file is, right now, compared with what the record says it was.
#: Also what colours a node in Person C's panel, which is why it is computed
#: once here rather than a second time (and re-hashed) by the layout.
MISSING, CHANGED, VERIFIED, UNKNOWN = "missing", "changed", "verified", "unknown"


def _entity_status(store, entity: dict[str, Any]) -> tuple[str, str]:
    """``(status, why)`` for one file.

    ``unknown`` covers three genuinely different situations — a layer that was
    never on disk, a file nothing was ever recorded about, and a format we could
    not read back — and they share an answer because in all three the honest
    report is that we cannot say, not that the file is fine.

    Uses Person B's whole fingerprint set rather than the byte hash alone, and
    treats `resaved` as unchanged: a GeoPackage rewritten by a different SQLite
    build has different bytes and identical data, and calling that an edit is
    the false positive `fingerprint/compare.py` exists to remove
    (docs/CONTRACT_schema.md, 2026-08-30).
    """
    path = entity["file_path"]
    name = entity["label"] or path or "a temporary layer"
    if not path:
        return UNKNOWN, ""  # a memory layer was never a file (CONTRACT_event.md)
    if not os.path.exists(path):
        return MISSING, f"{name} is no longer where we left it"

    recorded = store.get_fingerprint_set(entity["id"])
    if not recorded:
        return UNKNOWN, ""
    try:
        fresh = {f.hash_strategy: f.hash_value for f in hashing.fingerprint_dataset(path)}
    except hashing.FingerprintError:
        return UNKNOWN, ""

    verdict = compare.compare_fingerprint_sets(
        {k: v["hash_value"] for k, v in recorded.items()}, fresh
    )
    if verdict.verdict == compare.VERDICT_UNKNOWN:
        return UNKNOWN, ""
    if verdict.changed:
        return CHANGED, f"{name} — {verdict.explain()}"
    return VERIFIED, ""


def _inputs_exist(statuses: list[tuple[str, str]]) -> tuple[bool | None, str]:
    """Every input file is still where the record says it is.

    Files with no path are not counted: a memory layer was never on disk, so its
    absence is not a missing input.
    """
    on_disk = [s for s in statuses if s[0] != UNKNOWN or s[1]]
    gone = [why for status, why in statuses if status == MISSING]
    if gone:
        return False, "; ".join(gone)
    return (True, "") if on_disk else (None, "")


def _inputs_unchanged(statuses: list[tuple[str, str]]) -> tuple[bool | None, str]:
    """Contents still match what was recorded when the job ran.

    A file that is gone is not scored here. Awarding the contents check to a
    file nobody can read would let a deleted input cost 30 points instead of the
    55 it actually costs.
    """
    edited = [why for status, why in statuses if status == CHANGED]
    if edited:
        return False, "; ".join(edited)
    if any(status == VERIFIED for status, _ in statuses):
        return True, ""
    return None, ""


def _lookup(algorithm_id: str):
    """The Processing tool with this id, or ``None`` if we cannot get at it.

    RULES.md §2.5 — feature-detect. Outside QGIS there is no registry at all,
    which is a different thing from a tool being uninstalled, and the two are
    told apart by the callers below.
    """
    try:
        from qgis.core import QgsApplication
    except ImportError:
        return None
    try:
        return QgsApplication.processingRegistry().algorithmById(algorithm_id)
    except Exception:  # noqa: BLE001 — an audit reports, it does not crash
        return None


def _default_algorithm_probe(algorithm_id: str) -> bool | None:
    """Is this tool still installed? ``None`` when we cannot ask."""
    if _lookup("native:buffer") is None and _lookup(algorithm_id) is None:
        # Even the most ordinary tool in QGIS is absent, so there is no registry
        # here — we are outside QGIS and the honest answer is "we don't know".
        return None
    return _lookup(algorithm_id) is not None


def _default_parameter_names(algorithm_id: str) -> set[str] | None:
    """The settings this tool accepts today, or ``None`` if we cannot ask."""
    algorithm = _lookup(algorithm_id)
    if algorithm is None:
        return None
    try:
        return {d.name() for d in algorithm.parameterDefinitions()}
    except Exception:  # noqa: BLE001
        return None


def _environment_similar(
    recorded_agent: dict[str, Any] | None, current_qgis: str
) -> tuple[bool | None, str]:
    """The same major.minor QGIS the job originally ran on."""
    if recorded_agent is None or current_qgis == environment.UNKNOWN:
        return None, ""
    was = recorded_agent.get("qgis_version")
    if not was or was == environment.UNKNOWN:
        return None, ""
    if _series(was) == _series(current_qgis):
        return True, ""
    return False, f"QGIS {was} then, QGIS {current_qgis} now"


def _series(version: str) -> tuple[str, ...]:
    return tuple(version.split(".")[:2])


def _parameters_valid(
    activity: dict[str, Any], accepted: set[str] | None
) -> tuple[bool | None, str]:
    """Every recorded setting is one the tool still accepts.

    Needs the tool's own parameter definitions, so it is unanswerable wherever
    `algorithm_available` was unanswerable, and meaningless where the tool is
    gone entirely — `audit_workflow` only asks when the tool was found.
    """
    if accepted is None:
        return None, ""
    try:
        recorded = set(json.loads(activity["parameters_json"] or "{}"))
    except (TypeError, ValueError):
        return None, ""
    unknown = sorted(recorded - accepted)
    if unknown:
        return False, f"{activity['algorithm_id']} no longer takes {', '.join(unknown)}"
    return True, ""


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------


def audit_workflow(
    store,
    workflow_id: str,
    *,
    algorithm_probe: Callable[[str], bool | None] | None = None,
    parameter_names: Callable[[str], set[str] | None] | None = None,
    current_qgis: str | None = None,
) -> AuditResult:
    """Score one piece of work for whether it could still be reproduced.

    The three arguments after ``workflow_id`` are injected so that all five
    checks are exercisable without QGIS; each defaults to asking the real
    environment, which answers ``None`` when there is no QGIS to ask.
    """
    probe = algorithm_probe or _default_algorithm_probe
    names = parameter_names or _default_parameter_names
    current_qgis = current_qgis if current_qgis is not None else environment.qgis_version()

    graph = prov.ProvGraph.load(store, workflow_id)
    steps: list[StepFinding] = []

    #: entity id -> status. Every file is looked at once, however many jobs
    #: touch it, so a chain of ten steps does not re-read the same file ten
    #: times — the audit is a foreground action in the panel (§8.5).
    file_status: dict[str, tuple[str, str]] = {}

    def status_of(entity: dict[str, Any]) -> tuple[str, str]:
        if entity["id"] not in file_status:
            file_status[entity["id"]] = _entity_status(store, entity)
        return file_status[entity["id"]]

    for activity in graph.activities:
        inputs = graph.inputs_of(activity["id"])
        for output in graph.outputs_of(activity["id"]):
            status_of(output)  # not scored, but the panel colours it
        statuses = [status_of(e) for e in inputs]
        checks: dict[str, bool | None] = {}
        notes: dict[str, str] = {}

        for name, (ok, why) in (
            ("input_exists", _inputs_exist(statuses)),
            ("input_unchanged", _inputs_unchanged(statuses)),
            ("environment_similar",
             _environment_similar(graph.agent_for(activity["id"]), current_qgis)),
        ):
            checks[name] = ok
            if why:
                notes[name] = why

        available = probe(activity["algorithm_id"])
        checks["algorithm_available"] = available
        if available is False:
            notes["algorithm_available"] = f"{activity['algorithm_id']} is not installed"

        # Only ask what settings a tool accepts once we know the tool is there.
        accepted = names(activity["algorithm_id"]) if available is True else None
        valid, why = _parameters_valid(activity, accepted)
        checks["parameters_valid"] = valid
        if why:
            notes["parameters_valid"] = why

        steps.append(
            StepFinding(
                activity_id=activity["id"],
                label=activity["algorithm_name"] or activity["algorithm_id"],
                checks=checks,
                notes=notes,
            )
        )

    components: dict[str, float | None] = {}
    for name in WEIGHTS:
        ran = [s.checks[name] for s in steps if s.checks[name] is not None]
        components[name] = 100.0 * sum(ran) / len(ran) if ran else None

    scored = [(WEIGHTS[n], v) for n, v in components.items() if v is not None]
    weight = sum(w for w, _ in scored)
    overall = sum(w * v for w, v in scored) / weight if weight else 0.0

    return AuditResult(
        workflow_id=workflow_id,
        workflow_name=graph.workflow["name"],
        steps=steps,
        components=components,
        overall=round(overall, 1),
        file_status={key: status for key, (status, _) in file_status.items()},
    )


def persist(store, result: AuditResult) -> str:
    """Write the score through Person A's store (RULES.md §1.3 — C writes no SQL)."""
    return store.add_audit_result(
        workflow_id=result.workflow_id,
        overall_score=result.overall,
        details={
            "band": result.band,
            "weights": WEIGHTS,
            "steps": [
                {"activity_id": s.activity_id, "label": s.label,
                 "checks": s.checks, "notes": s.notes}
                for s in result.steps
            ],
        },
        **{f"{name}_score": value for name, value in result.components.items()},
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def report(result: AuditResult) -> str:
    """The research doc §4.3 Layer 5 report, in its own layout and vocabulary.

    For the paper and the panel. `plain_report` below is the one a demo may
    print — this one says "reproducibility", which RULES.md §7.5 bans.
    """
    lines = [
        "Reproducibility Audit Report",
        "═" * 31,
        f"Workflow: {result.workflow_name}",
        f"Steps audited: {len(result.steps)}",
        "─" * 30,
    ]
    for name, label in COMPONENT_LABELS:
        score = result.components[name]
        if score is None:
            lines.append(f"❔ {label + ':':<24} not checked (needs QGIS)")
            continue
        passed, ran = result.tally(name)
        mark = "✅" if score == 100 else "⚠️ "
        line = f"{mark} {label + ':':<24} {passed}/{ran} ({score:3.0f}%)"
        reasons = result.reasons(name)
        if reasons:
            line += f"  ← {reasons[0]}"
        lines.append(line)
    lines += [
        "─" * 30,
        f"OVERALL REPRODUCIBILITY SCORE: {result.overall:.0f}/100 ({result.band})",
    ]
    if any(v is None for v in result.components.values()):
        lines.append(
            "Scored over the checks that could be run; the rest need a running QGIS."
        )
    return "\n".join(lines)


#: The same finding, in the words RULES.md §7.5 requires a reviewer to hear.
_PLAIN_LABELS = {
    "input_exists": "the files it started from are still there",
    "input_unchanged": "those files still hold what they held",
    "algorithm_available": "QGIS still has the tools it used",
    "environment_similar": "QGIS is close enough to the version it ran on",
    "parameters_valid": "the settings still make sense to those tools",
}

_PLAIN_BANDS = {
    HIGH: "we could almost certainly run this again and get the same answer",
    MODERATE: "we could probably run this again, with some checking first",
    LOW: "we could not run this again as it stands",
}


def plain_report(result: AuditResult) -> str:
    """The same numbers with no jargon in them, for a demo (RULES.md §7.5)."""
    lines = [f"Could we run '{result.workflow_name}' again today?", ""]
    for name, _ in COMPONENT_LABELS:
        score = result.components[name]
        if score is None:
            lines.append(f"  ?  {_PLAIN_LABELS[name]} — we cannot tell without QGIS")
            continue
        passed, ran = result.tally(name)
        mark = "yes" if score == 100 else "no "
        lines.append(f"  {mark}  {_PLAIN_LABELS[name]} — {passed} of {ran} jobs")
        for reason in result.reasons(name)[:1]:
            lines.append(f"       {reason}")
    lines += ["", f"Score: {result.overall:.0f} out of 100 — {_PLAIN_BANDS[result.band]}."]

    # A score can stay high while a real problem has been found, because one
    # failed check is only worth its own share. Saying "almost certainly fine"
    # directly under a named changed file would be true about the arithmetic and
    # misleading about the work, so the findings get the last word.
    found = [name for name, value in result.components.items()
             if value is not None and value < 100]
    if found:
        lines.append(
            f"But {len(found)} of the checks found something — read the lines "
            f"marked 'no' above before trusting the number."
        )
    return "\n".join(lines)
