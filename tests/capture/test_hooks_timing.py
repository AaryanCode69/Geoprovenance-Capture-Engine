"""The pre-execution hook's start-time hand-off (A5).

No QGIS. RULES.md §6.1 — the QGIS-facing halves of hooks.py (writing the
script, setting ProcessingConfig) need a QGIS process and are left for
tests/capture/ under pytest-qgis. The hand-off itself is plain Python, and it
is the part that decides whether RQ2 can report a duration at all (§8.4).

Why this matters: the post-execution hook fires AFTER a run, so before A5
every job's start and end were the same instant and every duration was zero.
"""

from __future__ import annotations

import datetime as dt

import pytest

from geoprovenance.capture import hooks


@pytest.fixture(autouse=True)
def _clear_pending():
    """Module-level state — reset it around every test so order cannot matter."""
    hooks._pending_start = None
    yield
    hooks._pending_start = None


def test_the_pre_hook_leaves_a_start_time_the_post_hook_picks_up():
    hooks.handle_pre_execution({"alg": object()})
    assert hooks.take_pending_start() is not None


def test_the_start_time_is_consumed_so_it_cannot_be_reused():
    """One start time must never be attributed to two runs — that would invent
    a duration for the second."""
    hooks.handle_pre_execution({})
    assert hooks.take_pending_start() is not None
    assert hooks.take_pending_start() is None


def test_a_post_hook_with_no_pre_hook_gets_nothing_rather_than_a_guess():
    """The pre-A5 behaviour: the engine then defaults to now and the run looks
    instantaneous. Honest, and recorded in docs/capture_coverage.md."""
    assert hooks.take_pending_start() is None


def test_the_second_pre_hook_overwrites_the_first():
    """If the pre hook fires but the post hook does not — a crash, or an
    invocation path that runs only one of them — the stale time must not be
    handed to the NEXT algorithm. One slot, so it is overwritten rather than
    queued behind a leak."""
    hooks.handle_pre_execution({})
    first = hooks._pending_start
    hooks.handle_pre_execution({})
    second = hooks._pending_start
    assert first != second

    taken = hooks.take_pending_start()
    assert taken == second


def test_an_orphaned_start_time_is_discarded_rather_than_reported():
    """§8.4 — reporting an hours-old orphan as a duration would corrupt RQ2
    far worse than reporting nothing."""
    stale = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        seconds=hooks.MAX_PENDING_START_AGE_S + 60
    )
    hooks._pending_start = stale.isoformat()
    assert hooks.take_pending_start() is None


def test_a_start_time_from_the_future_is_discarded():
    """A clock change between the two hooks would otherwise produce a negative
    duration, which is worse than no duration."""
    ahead = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120)
    hooks._pending_start = ahead.isoformat()
    assert hooks.take_pending_start() is None


def test_a_malformed_start_time_is_discarded_not_propagated():
    hooks._pending_start = "sometime last tuesday"
    assert hooks.take_pending_start() is None


def test_the_pre_hook_never_raises_however_bad_the_namespace():
    """§5.1 [HARD] — it runs inside the user's processing run."""

    class Explosive(dict):
        def __iter__(self):
            raise RuntimeError("exploded")

    hooks.handle_pre_execution(Explosive())  # must not raise


def test_a_measurable_duration_survives_the_hand_off():
    """The actual point of A5's pre-hook: start and end are no longer equal."""
    hooks.handle_pre_execution({})
    started = hooks.take_pending_start()
    ended = dt.datetime.now(dt.timezone.utc).isoformat()

    assert dt.datetime.fromisoformat(ended) >= dt.datetime.fromisoformat(started)


def test_both_hook_scripts_are_generated_from_one_template():
    """They differ only in which handler they call, so a fix to the safety
    wrapper cannot land in one and be forgotten in the other."""
    pre = hooks.HOOK_TEMPLATE.format(
        plugin_parent="/x", handler="handle_pre_execution", when="pre")
    post = hooks.HOOK_TEMPLATE.format(
        plugin_parent="/x", handler="handle_post_execution", when="post")

    assert "handle_pre_execution(globals())" in pre
    assert "handle_post_execution(globals())" in post
    for script in (pre, post):
        # §5.1 — neither may let an exception out into the user's run.
        assert "except Exception" in script
