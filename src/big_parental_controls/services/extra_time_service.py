"""Parent side of the extra-time feature (big-parental-daemon, TimeExtra1).

Setting the PIN and granting minutes are reserved to administrators: the
D-Bus policy and the daemon both check that the caller is root or in wheel,
so the app (run by a parent) needs no pkexec prompt for these calls.
"""

from gi.repository import Gio, GLib

_DEST = "br.com.biglinux.ParentalDaemon"
_PATH = "/br/com/biglinux/ParentalDaemon"
_IFACE = "br.com.biglinux.TimeExtra1"


def _call(method: str, args: GLib.Variant | None, ret: str):
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    reply = bus.call_sync(_DEST, _PATH, _IFACE, method, args, GLib.VariantType(ret),
                          Gio.DBusCallFlags.NONE, 10000, None)
    return reply.unpack()[0]


def has_pin() -> bool | None:
    """True/False, or None when the daemon cannot be reached."""
    try:
        return bool(_call("HasParentPin", None, "(b)"))
    except GLib.Error:
        return None


def set_pin(pin: str) -> bool:
    try:
        return bool(_call("SetParentPin", GLib.Variant("(s)", (pin,)), "(b)"))
    except GLib.Error:
        return False


def grant(username: str, minutes: int) -> str:
    """Daemon result: "ok", "no_limit", "invalid", "denied" or "error"."""
    try:
        return _call("GrantExtra", GLib.Variant("(su)", (username, minutes)), "(s)")
    except GLib.Error:
        return "error"
