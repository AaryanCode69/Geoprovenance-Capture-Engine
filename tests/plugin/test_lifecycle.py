"""CleanupStack — the mechanism behind RULES.md §5.4.

No QGIS. This is deliberate: §5.4 (load -> unload -> load leaves no residue) is
the rule most likely to rot as the plugin grows, and this is the part of it
that can be verified on a machine with no QGIS installed.

    make test-plugin
"""

from __future__ import annotations

import pytest

from geoprovenance.lifecycle import CleanupStack


def test_undo_steps_run_in_reverse_order():
    """Teardown must mirror setup: a dock added after the menu action has to
    come off before it."""
    order = []
    stack = CleanupStack()
    stack.defer("first", lambda: order.append("first"))
    stack.defer("second", lambda: order.append("second"))
    stack.defer("third", lambda: order.append("third"))

    assert stack.unwind() == []
    assert order == ["third", "second", "first"]


def test_a_failing_step_does_not_strand_the_others():
    """§5.4 — a half-unloaded plugin leaves signals connected and monkeypatches
    installed, which is exactly the residue the rule exists to prevent."""
    done = []
    stack = CleanupStack()
    stack.defer("runs", lambda: done.append("bottom"))
    stack.defer("explodes", lambda: 1 / 0)
    stack.defer("also runs", lambda: done.append("top"))

    failures = stack.unwind()

    assert done == ["top", "bottom"]
    assert len(failures) == 1
    assert failures[0][0] == "explodes"
    assert isinstance(failures[0][1], ZeroDivisionError)


def test_unwind_never_raises_even_if_everything_fails():
    stack = CleanupStack()
    for i in range(3):
        stack.defer(f"broken {i}", lambda: (_ for _ in ()).throw(RuntimeError("nope")))

    failures = stack.unwind()  # must not raise

    assert len(failures) == 3
    assert all(isinstance(exc, RuntimeError) for _, exc in failures)


def test_the_stack_is_emptied_so_a_second_unload_is_a_no_op():
    """QGIS can call unload() more than once. Double-removing a menu action is
    how a reloaded plugin ends up in a broken state."""
    calls = []
    stack = CleanupStack()
    stack.defer("once", lambda: calls.append(1))

    stack.unwind()
    stack.unwind()

    assert calls == [1]
    assert len(stack) == 0


def test_the_stack_is_emptied_even_when_steps_fail():
    stack = CleanupStack()
    stack.defer("explodes", lambda: 1 / 0)

    assert len(stack.unwind()) == 1
    assert stack.unwind() == []  # nothing left to retry
    assert not stack


def test_a_non_callable_undo_is_rejected_at_registration():
    """Fail where the mistake is, not forty lines away inside unload()."""
    stack = CleanupStack()
    with pytest.raises(TypeError, match="not callable"):
        stack.defer("oops", "this is not a function")


def test_pending_reports_what_is_still_registered():
    stack = CleanupStack()
    stack.defer("close the database", lambda: None)
    stack.defer("remove the dock widget", lambda: None)

    assert stack.pending() == ["close the database", "remove the dock widget"]
    assert len(stack) == 2
    assert bool(stack) is True


def test_an_empty_stack_unwinds_to_nothing():
    assert CleanupStack().unwind() == []
    assert not CleanupStack()
