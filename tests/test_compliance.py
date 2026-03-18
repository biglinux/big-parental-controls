"""Tests for legal compliance — verify required legal references exist in source code.

These tests scan source files for required legal text, so they don't
need GTK or a running display.
"""

import pathlib

import pytest

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
UI_PAGES_DIR = SRC_DIR / "big_parental_controls" / "ui" / "pages"
UI_DIR = SRC_DIR / "big_parental_controls" / "ui"
INDICATOR_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "big-parental-controls"
    / "usr"
    / "bin"
    / "big-supervised-indicator"
)


def _read_source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TestLegalReferencesInWelcome:
    """Legal framework references must exist in the main view."""

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source(UI_PAGES_DIR / "main_view.py")

    def test_eca_digital_reference(self) -> None:
        assert "15.211/2025" in self.source

    def test_lgpd_reference(self) -> None:
        assert "13.709/2018" in self.source

    def test_gdpr_reference(self) -> None:
        assert "2016/679" in self.source

    def test_uk_children_code_reference(self) -> None:
        assert "Children's Code" in self.source

    def test_eu_dsa_reference(self) -> None:
        assert "2022/2065" in self.source


class TestSupportChannels:
    """Support channels must exist in the codebase."""

    @pytest.fixture(autouse=True)
    def _load_sources(self) -> None:
        main_view = _read_source(UI_PAGES_DIR / "main_view.py")
        indicator = _read_source(INDICATOR_PATH)
        self.all_sources = main_view + indicator

    def test_cvv_188_present(self) -> None:
        assert "CVV 188" in self.all_sources or "CVV" in self.all_sources

    def test_safernet_present(self) -> None:
        assert "SaferNet" in self.all_sources or "safernet" in self.all_sources

    def test_disque_100_present(self) -> None:
        assert "Disque 100" in self.all_sources


class TestConsentDialog:
    """Consent dialog must contain required legal text."""

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source(UI_DIR / "compliance.py")

    def test_lgpd_art14_mentioned(self) -> None:
        assert "LGPD Art. 14" in self.source

    def test_gdpr_art8_mentioned(self) -> None:
        assert "GDPR Art. 8" in self.source

    def test_data_retention_period(self) -> None:
        assert "30 days" in self.source

    def test_local_storage_statement(self) -> None:
        assert "no data is transmitted" in self.source.lower()

    def test_consent_button_exists(self) -> None:
        assert "I Understand and Consent" in self.source


class TestPrivacyStatements:
    """Privacy and data handling statements."""

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        detail = _read_source(UI_PAGES_DIR / "user_detail_page.py")
        compliance = _read_source(UI_DIR / "compliance.py")
        self.combined = detail + compliance

    def test_local_only_statement(self) -> None:
        assert "exclusively on this device" in self.combined

    def test_delete_data_right(self) -> None:
        assert "LGPD Art. 18" in self.combined

    def test_export_data_right(self) -> None:
        assert "GDPR Art. 20" in self.combined


class TestNoExternalTransmission:
    """Verify service code doesn't import HTTP/network libraries."""

    def test_no_requests_import(self) -> None:
        services_dir = SRC_DIR / "big_parental_controls" / "services"
        for py_file in services_dir.glob("*.py"):
            source = _read_source(py_file)
            assert "import requests" not in source, (
                f"HTTP library found in {py_file.name}"
            )
            assert "import urllib.request" not in source, (
                f"HTTP library found in {py_file.name}"
            )
            assert "import httpx" not in source, (
                f"HTTP library found in {py_file.name}"
            )

    def test_no_socket_in_activity(self) -> None:
        activity = _read_source(
            SRC_DIR / "big_parental_controls" / "services" / "activity_service.py"
        )
        assert "import socket" not in activity


class TestIndicatorTransparency:
    """Indicator must inform child about monitoring (Children's Code Std 11)."""

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source(INDICATOR_PATH)

    def test_monitoring_info_present(self) -> None:
        assert "shared with your parent" in self.source.lower()

    def test_usage_time_display(self) -> None:
        assert "computer time today" in self.source.lower()

    def test_break_reminder_exists(self) -> None:
        assert "break" in self.source.lower()


class TestDPIA:
    """Data Protection Impact Assessment document must exist."""

    def test_dpia_file_exists(self) -> None:
        dpia = (
            pathlib.Path(__file__).resolve().parent.parent / "DPIA.md"
        )
        assert dpia.exists(), "DPIA.md must exist at project root"

    def test_dpia_contains_required_sections(self) -> None:
        dpia = (
            pathlib.Path(__file__).resolve().parent.parent / "DPIA.md"
        )
        content = dpia.read_text(encoding="utf-8").lower()
        required = [
            "nature of processing",
            "risk assessment",
            "data minimization",
        ]
        for term in required:
            assert term in content, (
                f"DPIA.md missing section about '{term}'"
            )
