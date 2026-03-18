"""Tests for the DaemonClient D-Bus wrapper."""

from unittest.mock import patch

import pytest

from big_parental_controls.daemon_client.client import DaemonClient


@pytest.fixture
def client() -> DaemonClient:
    return DaemonClient()


class TestParseJsonString:
    """Tests for the busctl JSON response parser."""

    def test_valid_dict(self) -> None:
        raw = 's "{\\"2026-03-17\\": 120, \\"2026-03-18\\": 90}"'
        result = DaemonClient._parse_json_string(raw, {})
        assert result == {"2026-03-17": 120, "2026-03-18": 90}

    def test_valid_list(self) -> None:
        raw = 's "[1, 2, 3]"'
        result = DaemonClient._parse_json_string(raw, [])
        assert result == [1, 2, 3]

    def test_none_returns_default(self) -> None:
        assert DaemonClient._parse_json_string(None, {"fallback": True}) == {
            "fallback": True
        }

    def test_empty_string_returns_default(self) -> None:
        assert DaemonClient._parse_json_string("", []) == []

    def test_no_quotes_returns_default(self) -> None:
        assert DaemonClient._parse_json_string("b true", {}) == {}

    def test_malformed_json_returns_default(self) -> None:
        raw = 's "{not valid json}"'
        assert DaemonClient._parse_json_string(raw, []) == []

    def test_nested_json(self) -> None:
        raw = 's "[{\\"app\\": \\"firefox\\", \\"minutes\\": 45}]"'
        result = DaemonClient._parse_json_string(raw, [])
        assert len(result) == 1
        assert result[0]["app"] == "firefox"
        assert result[0]["minutes"] == 45


class TestGetMonitoredUsers:
    """Tests for parsing monitored users list."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_multiple_users(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = 'as 2 "minibruno" "tata"'
        result = client.get_monitored_users()
        assert result == ["minibruno", "tata"]

    @patch("big_parental_controls.daemon_client.client._call")
    def test_empty_list(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = "as 0"
        result = client.get_monitored_users()
        assert result == []

    @patch("big_parental_controls.daemon_client.client._call")
    def test_daemon_unavailable(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = None
        result = client.get_monitored_users()
        assert result == []


class TestEnableDisable:
    """Tests for monitoring toggle methods."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_enable_success(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = "b true"
        assert client.enable_user("minibruno", 1002) is True

    @patch("big_parental_controls.daemon_client.client._call")
    def test_enable_failure(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = None
        assert client.enable_user("minibruno", 1002) is False

    @patch("big_parental_controls.daemon_client.client._call")
    def test_disable_success(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = "b true"
        assert client.disable_user("minibruno") is True

    @patch("big_parental_controls.daemon_client.client._call")
    def test_disable_failure(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = "b false"
        assert client.disable_user("minibruno") is False


class TestGetDailyTotals:
    """Tests for daily usage parsing."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_valid_response(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = (
            's "{\\"2026-03-17\\": 120, \\"2026-03-18\\": 45}"'
        )
        result = client.get_daily_totals("minibruno", 2)
        assert result == {"2026-03-17": 120, "2026-03-18": 45}

    @patch("big_parental_controls.daemon_client.client._call")
    def test_daemon_down(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = None
        result = client.get_daily_totals("minibruno")
        assert result == {}


class TestGetHourlyDistribution:
    """Tests for hourly distribution parsing."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_valid_24_slots(self, mock_call, client: DaemonClient) -> None:
        slots = [0] * 24
        slots[10] = 30
        slots[14] = 60
        mock_call.return_value = f's "{str(slots).replace(" ", "")}"'
        result = client.get_hourly_distribution("minibruno")
        assert len(result) == 24
        assert result[10] == 30
        assert result[14] == 60

    @patch("big_parental_controls.daemon_client.client._call")
    def test_invalid_length_returns_zeros(
        self, mock_call, client: DaemonClient
    ) -> None:
        mock_call.return_value = 's "[1, 2, 3]"'
        result = client.get_hourly_distribution("minibruno")
        assert result == [0] * 24

    @patch("big_parental_controls.daemon_client.client._call")
    def test_daemon_down(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = None
        result = client.get_hourly_distribution("minibruno")
        assert result == [0] * 24


class TestGetAppUsage:
    """Tests for app usage parsing."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_valid_apps(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = (
            's "[{\\"app\\": \\"firefox\\", '
            '\\"display_name\\": \\"Firefox\\", '
            '\\"minutes\\": 90}]"'
        )
        result = client.get_app_usage("minibruno")
        assert len(result) == 1
        assert result[0]["app"] == "firefox"
        assert result[0]["minutes"] == 90

    @patch("big_parental_controls.daemon_client.client._call")
    def test_empty_usage(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = 's "[]"'
        result = client.get_app_usage("minibruno")
        assert result == []


class TestIsAvailable:
    """Tests for daemon availability check."""

    @patch("big_parental_controls.daemon_client.client._call")
    def test_available(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = 'v s "1.0.0"'
        assert client.is_available() is True

    @patch("big_parental_controls.daemon_client.client._call")
    def test_not_available(self, mock_call, client: DaemonClient) -> None:
        mock_call.return_value = None
        assert client.is_available() is False
