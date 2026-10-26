"""Errors."""

from pyjs import js


@js
class BugIndicatingError(Exception):
    """An internal invariant failed; callers provide a specific message."""


@js
def on_unexpected_error(error: object) -> None:
    print(error)
