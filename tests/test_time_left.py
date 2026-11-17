"""Tests for the remaining-time logic shared by big-time-left / big-time-tray."""

import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from big_parental_controls.services import time_left as tl  # noqa: E402

DAEMON_SRC = REPO_ROOT / "big-age-signal" / "src" / "main.rs"
MONDAY = datetime(2026, 11, 16, 20, 0)  # a Monday, 20:00


class TempFiles(unittest.TestCase):
    """Points time_left at a temporary state dir and time.conf."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._saved = (tl.STATE_DIR, tl.TIME_CONF)
        tl.STATE_DIR = self.dir
        tl.TIME_CONF = self.dir / "time.conf"

    def tearDown(self):
        tl.STATE_DIR, tl.TIME_CONF = self._saved
        self._tmp.cleanup()

    def write(self, name: str, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.dir / name).write_text(text)


class TestFmt(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual(tl.fmt(5), "5 min")
        self.assertEqual(tl.fmt(65), "1h05")
        self.assertEqual(tl.fmt(-3), "0 min")


class TestDayApplies(unittest.TestCase):
    def test_codes(self):
        self.assertTrue(tl.day_applies("Al", 6))
        self.assertTrue(tl.day_applies("Wk", 0))
        self.assertFalse(tl.day_applies("Wk", 5))
        self.assertTrue(tl.day_applies("Wd", 6))
        self.assertTrue(tl.day_applies("MoWe", 2))
        self.assertFalse(tl.day_applies("MoWe", 1))


class TestExtraSettings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(
            tl.extra_settings({}),
            {"step": tl.EXTRA_STEP_MIN, "max_requests": tl.EXTRA_MAX_REQUESTS,
             "extend_schedule": False})

    def test_clamped_and_invalid(self):
        s = tl.extra_settings({"extra": {"step": 999, "max_requests": -4,
                                         "extend_schedule": True}})
        self.assertEqual((s["step"], s["max_requests"], s["extend_schedule"]), (120, 0, True))
        s = tl.extra_settings({"extra": {"step": "abc"}})
        self.assertEqual(s["step"], tl.EXTRA_STEP_MIN)


class TestScheduleLeft(TempFiles):
    def test_no_rule(self):
        self.assertIsNone(tl.schedule_left("kid", MONDAY))
        self.write("time.conf", "*;*;other;Al0800-2100\n")
        self.assertIsNone(tl.schedule_left("kid", MONDAY))

    def test_inside_and_outside(self):
        self.write("time.conf", "*;*;kid;Al0800-2100\n")
        self.assertEqual(tl.schedule_left("kid", MONDAY), (60, "21:00"))
        self.assertEqual(tl.schedule_left("kid", MONDAY.replace(hour=22)), (0, None))

    def test_shift_pushes_the_end(self):
        self.write("time.conf", "*;*;kid;Al0800-2100\n")
        late = MONDAY.replace(hour=21, minute=5)
        self.assertEqual(tl.schedule_left("kid", late), (0, None))
        self.assertEqual(tl.schedule_left("kid", late, shift=15), (10, "21:15"))

    def test_day_specific_ranges(self):
        self.write("time.conf", "*;*;kid;Wd1000-2200|Wk0800-2030\n")
        self.assertEqual(tl.schedule_left("kid", MONDAY), (30, "20:30"))


class TestCompute(TempFiles):
    def setUp(self):
        super().setUp()
        self.today = date.today().isoformat()

    def test_quota_with_bonus(self):
        self.write("time-limits.json", {"kid": {"daily_minutes": 60}})
        self.write("time-state.json", {"_date": self.today, "kid": 50})
        self.write("time-extra.json", {"_date": self.today, "kid": {"minutes": 15, "requests": 1}})
        info = tl.compute("kid", MONDAY)
        self.assertEqual(info["quota_left"], 25)
        self.assertEqual(info["bonus"], 15)
        self.assertEqual(info["requests_left"], tl.EXTRA_MAX_REQUESTS - 1)

    def test_old_state_is_ignored(self):
        self.write("time-limits.json", {"kid": {"daily_minutes": 60}})
        self.write("time-state.json", {"_date": "2000-01-01", "kid": 50})
        self.write("time-extra.json", {"_date": "2000-01-01", "kid": {"minutes": 15}})
        info = tl.compute("kid", MONDAY)
        self.assertEqual((info["quota_left"], info["bonus"]), (60, 0))

    def test_no_limit_means_no_request(self):
        info = tl.compute("kid", MONDAY)
        self.assertIsNone(info["remaining"])
        self.assertEqual(info["requests_left"], 0)

    def test_schedule_only_extension(self):
        self.write("time.conf", "*;*;kid;Al0800-2000\n")
        self.write("time-limits.json", {"kid": {"extra": {"extend_schedule": True}}})
        self.write("time-extra.json", {"_date": self.today, "kid": {"minutes": 10}})
        info = tl.compute("kid", MONDAY.replace(minute=5))
        self.assertEqual((info["sched_left"], info["sched_end"]), (5, "20:10"))
        self.assertEqual(info["requests_left"], tl.EXTRA_MAX_REQUESTS)

    def test_extension_ignored_when_disabled(self):
        self.write("time.conf", "*;*;kid;Al0800-2000\n")
        self.write("time-extra.json", {"_date": self.today, "kid": {"minutes": 10}})
        info = tl.compute("kid", MONDAY.replace(minute=5))
        self.assertEqual(info["sched_left"], 0)


class TestTexts(unittest.TestCase):
    """Untranslated (English) texts; translations come from the .po files."""

    def test_result_text(self):
        self.assertIn("+10", tl.result_text("ok:10"))
        self.assertIn("7", tl.result_text("locked:7"))
        self.assertEqual(tl.result_text("weird"), tl.result_text("error"))

    def test_alert_text(self):
        summary, body = tl.alert_text("daily-warn", 1)
        self.assertIn("1", summary)
        self.assertIn("minute.", body)
        self.assertIn("minutes.", tl.alert_text("schedule-warn", 5)[1])


class TestDaemonDefaults(unittest.TestCase):
    """time_left.py and big-parental-daemon must agree on the defaults."""

    def test_same_defaults(self):
        src = DAEMON_SRC.read_text(encoding="utf-8")
        for name in ("EXTRA_STEP_MIN", "EXTRA_MAX_REQUESTS"):
            m = re.search(rf"const {name}: u32 = (\d+);", src)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m[1]), getattr(tl, name), name)


if __name__ == "__main__":
    unittest.main()
