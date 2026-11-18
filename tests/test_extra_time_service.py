"""Tests for extra_time_service D-Bus calls (fake GIR, no daemon needed)."""

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

MODULE = "big_parental_controls.services.extra_time_service"


class FakeGLibError(Exception):
    pass


@pytest.fixture
def svc():
    glib = MagicMock()
    glib.Error = FakeGLibError
    glib.Variant = MagicMock(side_effect=lambda sig, val: (sig, val))
    glib.VariantType = lambda sig: sig
    gio = MagicMock()
    bus = gio.bus_get_sync.return_value

    repository = ModuleType("gi.repository")
    repository.Gio = gio
    repository.GLib = glib
    gi = ModuleType("gi")
    gi.repository = repository

    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        sys.modules.pop(MODULE, None)
        module = importlib.import_module(MODULE)
        yield module, bus
    sys.modules.pop(MODULE, None)


def _reply(bus: MagicMock, value: object) -> None:
    bus.call_sync.return_value.unpack.return_value = (value,)


def _sent(bus: MagicMock) -> tuple:
    args = bus.call_sync.call_args.args
    return args[3], args[4], args[5]  # method, params, reply type


def test_grant_sends_user_and_minutes(svc) -> None:
    module, bus = svc
    _reply(bus, "ok")
    assert module.grant("lana", 15) == "ok"
    assert _sent(bus) == ("GrantExtra", ("(su)", ("lana", 15)), "(s)")


def test_set_pin(svc) -> None:
    module, bus = svc
    _reply(bus, True)
    assert module.set_pin("1234") is True
    assert _sent(bus) == ("SetParentPin", ("(s)", ("1234",)), "(b)")


def test_has_pin(svc) -> None:
    module, bus = svc
    _reply(bus, False)
    assert module.has_pin() is False
    assert _sent(bus)[0] == "HasParentPin"


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda m: m.has_pin(), None),
        (lambda m: m.set_pin("1234"), False),
        (lambda m: m.grant("lana", 15), "error"),
    ],
)
def test_daemon_unreachable(svc, call, expected) -> None:
    module, bus = svc
    bus.call_sync.side_effect = FakeGLibError()
    assert call(module) == expected
