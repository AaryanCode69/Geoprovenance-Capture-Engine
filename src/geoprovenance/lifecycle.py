"""Teardown bookkeeping for plugin load/unload.

Owner: Person A.  Sub-phase: A1.

Imports no QGIS and no PyQt, deliberately: RULES.md §5.4 is the rule most
likely to be got wrong, and this is the part of it that can be tested on a
machine with no QGIS installed.

    §5.4 [HARD] — unload() must disconnect every signal, stop every QTimer,
    un-patch every monkeypatch, close the database connection, and restore the
    user's POST_EXECUTION_SCRIPT. Load -> unload -> load must leave no residue
    and produce no log errors.

Remembering to undo each of those in a hand-written unload() is exactly the
kind of thing that rots as the plugin grows. Instead every setup step registers
its own undo at the moment it succeeds, and unload() unwinds the stack.

    stack = CleanupStack()
    action = QAction(...); menu.addAction(action)
    stack.defer("remove menu action", lambda: menu.removeAction(action))
    ...
    failures = stack.unwind()   # LIFO, never raises

Unwinding is last-in-first-out because teardown must mirror setup: a dock
widget added after the menu action has to come off before it.
"""

from __future__ import annotations

from typing import Callable


class CleanupStack:
    """A LIFO stack of undo callables that always drains completely."""

    def __init__(self) -> None:
        self._entries: list[tuple[str, Callable[[], None]]] = []

    def defer(self, description: str, undo: Callable[[], None]) -> None:
        """Register ``undo``, to be run on unwind. Call it right after the
        matching setup step succeeds, never in a batch at the end."""
        if not callable(undo):
            raise TypeError(f"undo for {description!r} is not callable")
        self._entries.append((description, undo))

    def unwind(self) -> list[tuple[str, BaseException]]:
        """Run every registered undo, most recent first. Never raises.

        One broken teardown step must not strand the rest — a half-unloaded
        plugin leaves signals connected and monkeypatches installed, which is
        precisely the residue §5.4 exists to prevent. Failures are returned for
        the caller to log rather than swallowed silently.

        The stack is emptied even if steps fail, so unwinding twice is a no-op
        and a second unload() cannot double-remove anything.
        """
        failures: list[tuple[str, BaseException]] = []
        while self._entries:
            description, undo = self._entries.pop()
            try:
                undo()
            except BaseException as exc:  # noqa: BLE001 — reported, not raised
                failures.append((description, exc))
        return failures

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def pending(self) -> list[str]:
        """Descriptions still registered, most recent last. For diagnostics."""
        return [description for description, _ in self._entries]
