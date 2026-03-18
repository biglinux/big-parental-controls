"""Wrapper around libmalcontent GIR bindings for managing app filters and session limits."""

import gi

gi.require_version("Malcontent", "0")
from gi.repository import Gio, GLib, Malcontent

_V = Malcontent.AppFilterOarsValue

OARS_PRESETS: dict[str, dict[str, Malcontent.AppFilterOarsValue]] = {
    "child": {
        "violence-cartoon": _V.NONE,
        "violence-fantasy": _V.NONE,
        "violence-realistic": _V.NONE,
        "violence-bloodshed": _V.NONE,
        "violence-sexual": _V.NONE,
        "violence-desecration": _V.NONE,
        "violence-slavery": _V.NONE,
        "violence-worship": _V.NONE,
        "drugs-alcohol": _V.NONE,
        "drugs-narcotics": _V.NONE,
        "drugs-tobacco": _V.NONE,
        "sex-nudity": _V.NONE,
        "sex-themes": _V.NONE,
        "sex-homosexuality": _V.NONE,
        "sex-prostitution": _V.NONE,
        "sex-adultery": _V.NONE,
        "sex-appearance": _V.NONE,
        "language-profanity": _V.NONE,
        "language-humor": _V.MILD,
        "language-discrimination": _V.NONE,
        "social-chat": _V.MILD,
        "social-info": _V.MILD,
        "social-audio": _V.NONE,
        "social-location": _V.NONE,
        "social-contacts": _V.NONE,
        "money-purchasing": _V.NONE,
        "money-gambling": _V.NONE,
    },
    "preteen": {
        "violence-cartoon": _V.MILD,
        "violence-fantasy": _V.MILD,
        "violence-realistic": _V.NONE,
        "violence-bloodshed": _V.NONE,
        "violence-sexual": _V.NONE,
        "violence-desecration": _V.NONE,
        "violence-slavery": _V.NONE,
        "violence-worship": _V.NONE,
        "drugs-alcohol": _V.NONE,
        "drugs-narcotics": _V.NONE,
        "drugs-tobacco": _V.NONE,
        "sex-nudity": _V.NONE,
        "sex-themes": _V.NONE,
        "sex-homosexuality": _V.MILD,
        "sex-prostitution": _V.NONE,
        "sex-adultery": _V.NONE,
        "sex-appearance": _V.MILD,
        "language-profanity": _V.MILD,
        "language-humor": _V.MILD,
        "language-discrimination": _V.NONE,
        "social-chat": _V.MODERATE,
        "social-info": _V.MODERATE,
        "social-audio": _V.MILD,
        "social-location": _V.NONE,
        "social-contacts": _V.MILD,
        "money-purchasing": _V.NONE,
        "money-gambling": _V.NONE,
    },
    "teen": {
        "violence-cartoon": _V.MODERATE,
        "violence-fantasy": _V.MODERATE,
        "violence-realistic": _V.MILD,
        "violence-bloodshed": _V.MILD,
        "violence-sexual": _V.NONE,
        "violence-desecration": _V.NONE,
        "violence-slavery": _V.MILD,
        "violence-worship": _V.MILD,
        "drugs-alcohol": _V.MILD,
        "drugs-narcotics": _V.NONE,
        "drugs-tobacco": _V.MILD,
        "sex-nudity": _V.NONE,
        "sex-themes": _V.MILD,
        "sex-homosexuality": _V.MODERATE,
        "sex-prostitution": _V.NONE,
        "sex-adultery": _V.NONE,
        "sex-appearance": _V.MODERATE,
        "language-profanity": _V.MODERATE,
        "language-humor": _V.MODERATE,
        "language-discrimination": _V.MILD,
        "social-chat": _V.INTENSE,
        "social-info": _V.INTENSE,
        "social-audio": _V.MODERATE,
        "social-location": _V.MILD,
        "social-contacts": _V.MODERATE,
        "money-purchasing": _V.MILD,
        "money-gambling": _V.NONE,
    },
    "young-adult": {
        "violence-cartoon": _V.INTENSE,
        "violence-fantasy": _V.INTENSE,
        "violence-realistic": _V.MODERATE,
        "violence-bloodshed": _V.MODERATE,
        "violence-sexual": _V.MILD,
        "violence-desecration": _V.MILD,
        "violence-slavery": _V.MODERATE,
        "violence-worship": _V.MODERATE,
        "drugs-alcohol": _V.MODERATE,
        "drugs-narcotics": _V.MILD,
        "drugs-tobacco": _V.MODERATE,
        "sex-nudity": _V.MILD,
        "sex-themes": _V.MODERATE,
        "sex-homosexuality": _V.INTENSE,
        "sex-prostitution": _V.MILD,
        "sex-adultery": _V.MILD,
        "sex-appearance": _V.INTENSE,
        "language-profanity": _V.INTENSE,
        "language-humor": _V.INTENSE,
        "language-discrimination": _V.MODERATE,
        "social-chat": _V.INTENSE,
        "social-info": _V.INTENSE,
        "social-audio": _V.INTENSE,
        "social-location": _V.MODERATE,
        "social-contacts": _V.INTENSE,
        "money-purchasing": _V.MODERATE,
        "money-gambling": _V.MILD,
    },
}


class MalcontentService:
    """Service for managing parental controls via libmalcontent."""

    def __init__(self) -> None:
        self._connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self._manager = Malcontent.Manager.new(self._connection)

    def is_available(self) -> bool:
        """Check if malcontent is usable on this system."""
        try:
            Malcontent.Manager.new(self._connection)
        except GLib.Error:
            return False
        else:
            return True

    def get_app_filter(self, uid: int) -> Malcontent.AppFilter:
        """Get the app filter for a user UID."""
        return self._manager.get_app_filter(
            uid,
            Malcontent.ManagerGetValueFlags.INTERACTIVE,
            None,
        )

    def set_app_filter(
        self,
        uid: int,
        blocked_paths: list[str] | None = None,
        allowed_paths: list[str] | None = None,
        oars_values: dict[str, Malcontent.AppFilterOarsValue] | None = None,
        allow_user_installation: bool = False,
        allow_system_installation: bool = False,
    ) -> None:
        """Set app filter for a user UID."""
        builder = Malcontent.AppFilterBuilder.new()

        if blocked_paths:
            for path in blocked_paths:
                builder.blocklist_path(path)

        builder.set_allow_user_installation(allow_user_installation)
        builder.set_allow_system_installation(allow_system_installation)

        if oars_values:
            for section, value in oars_values.items():
                builder.set_oars_value(section, value)

        app_filter = builder.end()
        self._manager.set_app_filter(
            uid,
            app_filter,
            Malcontent.ManagerSetValueFlags.INTERACTIVE,
            None,
        )

    def get_session_limits(self, uid: int) -> Malcontent.SessionLimits:
        """Get session limits for a user UID."""
        return self._manager.get_session_limits(
            uid,
            Malcontent.ManagerGetValueFlags.INTERACTIVE,
            None,
        )

    def set_session_limits(
        self,
        uid: int,
        daily_start_secs: int,
        daily_end_secs: int,
    ) -> None:
        """Set daily session schedule for a user UID."""
        builder = Malcontent.SessionLimitsBuilder.new()
        builder.set_daily_schedule(daily_start_secs, daily_end_secs)
        limits = builder.end()
        self._manager.set_session_limits(
            uid,
            limits,
            Malcontent.ManagerSetValueFlags.INTERACTIVE,
            None,
        )

    def is_app_blocked(self, uid: int, app_path: str) -> bool:
        """Check if a specific app path is blocked for a user."""
        try:
            app_filter = self.get_app_filter(uid)
            return not app_filter.is_path_allowed(app_path)
        except GLib.Error:
            return False

    def is_appinfo_allowed(self, uid: int, app_info: Gio.AppInfo) -> bool:
        """Check if an AppInfo is allowed by the user's OARS filter."""
        try:
            app_filter = self.get_app_filter(uid)
            return app_filter.is_appinfo_allowed(app_info)
        except GLib.Error:
            return True

    def get_oars_blocked_apps(self, uid: int) -> list[Gio.AppInfo]:
        """Get all installed apps blocked by the user's OARS filter."""
        try:
            app_filter = self.get_app_filter(uid)
        except GLib.Error:
            return []
        blocked = []
        for app_info in Gio.AppInfo.get_all():
            try:
                if not app_filter.is_appinfo_allowed(app_info):
                    blocked.append(app_info)
            except GLib.Error:
                continue
        return blocked

    def clear_app_filter(self, uid: int) -> None:
        """Remove all app filter restrictions for a user."""
        builder = Malcontent.AppFilterBuilder.new()
        builder.set_allow_user_installation(True)
        builder.set_allow_system_installation(True)
        app_filter = builder.end()
        self._manager.set_app_filter(
            uid,
            app_filter,
            Malcontent.ManagerSetValueFlags.INTERACTIVE,
            None,
        )
