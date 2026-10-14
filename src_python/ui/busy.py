"""Wait cursor for operations that run on the UI thread."""

from __future__ import annotations

import functools
import inspect
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@contextmanager
def busy_cursor():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def with_busy_cursor(method):
    """Decorate a slot; extra signal arguments (e.g. ``checked``) are dropped."""
    parameters = inspect.signature(method).parameters.values()
    variadic = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters)
    count = len(inspect.signature(method).parameters)

    @functools.wraps(method)
    def wrapper(*args):
        with busy_cursor():
            return method(*(args if variadic else args[:count]))

    return wrapper
