"""Run blocking work off the GTK main thread."""

import threading
from typing import Callable

from gi.repository import GLib


def run_async(
    task: Callable,
    callback: Callable | None = None,
    error_callback: Callable | None = None,
) -> None:
    """Execute *task* in a background thread.

    When *task* finishes, *callback(result)* is scheduled on the main
    thread via ``GLib.idle_add``.  If *task* raises, *error_callback(exc)*
    is called instead (also on the main thread).
    """

    def _worker() -> None:
        try:
            result = task()
        except Exception as exc:  # noqa: BLE001
            if error_callback:
                GLib.idle_add(_on_error, exc)
        else:
            if callback:
                GLib.idle_add(_on_done, result)

    def _on_done(result: object) -> bool:
        callback(result)
        return GLib.SOURCE_REMOVE

    def _on_error(exc: Exception) -> bool:
        error_callback(exc)
        return GLib.SOURCE_REMOVE

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
