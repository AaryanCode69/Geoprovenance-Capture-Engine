"""Shared output helpers for the three review demos.

This module *is* RULES.md §7.7 in executable form. Use it rather than hand-rolling
print statements, so all three demos look identical and none of them drifts.

    RULES.md §7.3 — imports nothing but the standard library, so a demo runs on a
    machine with no QGIS installed, offline, in a review room.

Usage
    from _presenter import Demo

    demo = Demo(
        review="1",
        claim="QGIS ran a job and we wrote it down automatically.",
        before="Nothing was recorded. Close QGIS and the history was gone.",
        after="Every job QGIS runs is written down by itself, as it happens.",
        steps=3,
    )
    with demo.step("Pretending QGIS just ran 'Buffer'"):
        ...
    demo.readback({"Someone ran": "Buffer", "On the file": "roads.shp"})
    demo.limitation("We only notice jobs run through the Processing toolbox.")
    raise SystemExit(demo.finish())
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import pathlib
import shutil
import sys
import traceback

WIDTH = 56
RULE = "═" * WIDTH

#: RULES.md §7.5 — these must never reach a reviewer's eyes. The linter below
#: checks everything this module prints and complains during rehearsal.
BANNED_WORDS = (
    "entity", "entities", "activity record", "prov-o", "prov_o", "w3c prov",
    "dag", "sha-256", "sha256", "hash", "provenance", "schema", "ddl",
    "commit", "git", "branch", "repository", "repo", "transaction", "rollback",
    "wal", "sqlite", "normalizer", "serialization", "serialize", "uuid",
    "wasgeneratedby", "wasderivedfrom", "wasassociatedwith", "singleton",
    "capture completeness", "runtime overhead", "deduplication", "dedup",
)

_SCRATCH = pathlib.Path(__file__).resolve().parent / "_scratch"


def human_time(when: _dt.datetime | str) -> str:
    """'18 Aug 2026, 2:31 pm' — never a raw ISO timestamp (RULES.md §7.7)."""
    if isinstance(when, str):
        when = _dt.datetime.fromisoformat(when)
    hour = when.hour % 12 or 12
    meridiem = "am" if when.hour < 12 else "pm"
    return f"{when.day} {when:%b %Y}, {hour}:{when:%M} {meridiem}"


def human_size(num_bytes: int) -> str:
    """'42 KB' — sized for a human, not a machine."""
    for unit in ("bytes", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "bytes" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} GB"


def scratch_dir() -> pathlib.Path:
    """A wiped-clean working directory.

    RULES.md §7.2 [HARD] — a demo must never pass because of yesterday's
    leftovers, and must produce identical output when run twice in a row.
    """
    if _SCRATCH.exists():
        shutil.rmtree(_SCRATCH)
    _SCRATCH.mkdir(parents=True)
    return _SCRATCH


def lint(text: str) -> list[str]:
    """Return the banned words found in ``text`` (RULES.md §7.5)."""
    lowered = text.lower()
    return sorted({word for word in BANNED_WORDS if word in lowered})


class Demo:
    """Prints the fixed §7.7 demo format and tracks pass/fail."""

    def __init__(self, review: str, claim: str, before: str, after: str, steps: int):
        self.review = review
        self.claim = claim
        self.total = steps
        self.index = 0
        self.passed = 0
        self._transcript: list[str] = []
        self._limitations: list[str] = []

        self._say("")
        self._say(RULE)
        self._say(f"  GeoProvenance — Review {review} Demo")
        self._say(f'  "{claim}"')
        self._say(RULE)
        self._say("")
        self._say(f"BEFORE this phase:  {before}")
        self._say(f"AFTER  this phase:  {after}")
        self._say("")

    # ---- output ---------------------------------------------------------

    def _say(self, line: str = "") -> None:
        self._transcript.append(line)
        print(line)

    @contextlib.contextmanager
    def step(self, description: str):
        """One numbered step. Prints OK, or FAIL with the reason."""
        self.index += 1
        label = f"[{self.index}/{self.total}] {description}..."
        try:
            yield
        except Exception as exc:  # noqa: BLE001 — a demo reports, it does not crash
            self._say(f"{label:<{WIDTH - 6}}FAIL")
            self._say(f"        {type(exc).__name__}: {exc}")
            self._say("".join("        " + ln for ln in traceback.format_exc().splitlines(True)))
        else:
            self.passed += 1
            self._say(f"{label:<{WIDTH - 6}}OK")

    def readback(self, fields: dict[str, str]) -> None:
        """The payoff: real captured data, in plain English, neatly aligned."""
        self._say("")
        pad = max((len(k) for k in fields), default=0)
        for key, value in fields.items():
            self._say(f"  {key:<{pad}} : {value}")
        self._say("")

    def note(self, text: str) -> None:
        self._say(f"  {text}")

    def limitation(self, text: str) -> None:
        """RULES.md §7.10 [HARD] — every demo states at least one honest limit."""
        self._limitations.append(text)

    # ---- finish ---------------------------------------------------------

    def finish(self, strict: bool = True) -> int:
        """Print the tail and return the process exit code (0 pass, 1 fail)."""
        if not self._limitations:
            raise AssertionError(
                "RULES.md §7.10: every demo must call limitation() at least once. "
                "An unmentioned gap that a reviewer finds costs more than a "
                "mentioned one."
            )
        self._say("WHAT WE STILL CAN'T DO:")
        for item in self._limitations:
            self._say(f"  {item}")
        self._say("")

        ok = self.passed == self.total
        mark = "✅" if ok else "❌"
        self._say(f"{mark} {self.passed} of {self.total} checks passed.")
        self._say("")

        if strict:
            offenders = lint("\n".join(self._transcript))
            if offenders:
                self._say("⚠️  REHEARSAL WARNING (RULES.md §7.5) — jargon in the output:")
                self._say(f"      {', '.join(offenders)}")
                self._say("    Rewrite these in plain words before the review.")
                self._say("    See the glossary in CLAUDE.md §8.")
                self._say("")

        return 0 if ok else 1


def require_python() -> None:
    """RULES.md §2.1 — fail early and legibly on the wrong interpreter."""
    if sys.version_info < (3, 10):
        raise SystemExit(
            f"This project targets the Python bundled with QGIS 3.34 LTS (3.10 or "
            f"3.11). You are running {sys.version.split()[0]}. See RULES.md §2.1."
        )
