"""Tests for MalcontentService.set_session_limits across libmalcontent versions.

libmalcontent 0.14 changed set_daily_schedule(start, end) into
set_daily_schedule(enforced, start, end). The service inspects the
introspected signature; these tests fake the GIR module so they run
without libmalcontent installed.
"""

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

MODULE = "big_parental_controls.services.malcontent_service"


def _load_service(arg_count: int | None) -> tuple[ModuleType, MagicMock]:
    """Import the service with a fake Malcontent exposing `arg_count` args.

    arg_count=None simulates bindings without get_arguments().
    """
    malcontent = MagicMock()
    set_daily = malcontent.SessionLimitsBuilder.set_daily_schedule
    if arg_count is None:
        del set_daily.get_arguments
    else:
        set_daily.get_arguments.return_value = [object()] * arg_count

    repository = ModuleType("gi.repository")
    repository.Gio = MagicMock()
    repository.GLib = MagicMock()
    repository.Malcontent = malcontent
    gi = ModuleType("gi")
    gi.require_version = lambda *_: None
    gi.repository = repository

    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        sys.modules.pop(MODULE, None)
        module = importlib.import_module(MODULE)
    sys.modules.pop(MODULE, None)
    return module, malcontent


@pytest.mark.parametrize(
    ("arg_count", "expected"),
    [
        (3, (True, 3600, 7200)),  # libmalcontent >= 0.14
        (2, (3600, 7200)),  # older libmalcontent
        (None, (3600, 7200)),  # no introspection info
    ],
)
def test_set_daily_schedule_matches_signature(arg_count: int | None, expected: tuple) -> None:
    module, malcontent = _load_service(arg_count)
    builder = malcontent.SessionLimitsBuilder.new.return_value

    service = module.MalcontentService()
    service.set_session_limits(1001, 3600, 7200)

    builder.set_daily_schedule.assert_called_once_with(*expected)
    service._manager.set_session_limits.assert_called_once_with(
        1001,
        builder.end.return_value,
        malcontent.ManagerSetValueFlags.INTERACTIVE,
        None,
    )
