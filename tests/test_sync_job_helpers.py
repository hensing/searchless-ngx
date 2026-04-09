"""
Tests for pure helper methods in SyncJob.
These are free of external dependencies — no mocking of APIs or vector stores needed.
"""
import pytest
from semantic.sync_job import SyncJob
from api.paperless_client import PaperlessAPIClient


@pytest.fixture
def sync_job(paperless_client: PaperlessAPIClient):
    return SyncJob(client=paperless_client)


# ---------------------------------------------------------------------------
# _format_custom_field_value
# ChromaDB only accepts str/int/float/bool. This function is the boundary
# that converts Paperless custom field values to safe primitives.
# ---------------------------------------------------------------------------

class TestFormatCustomFieldValue:
    def test_none_returns_empty_string_regardless_of_type(self, sync_job):
        """None must always return "" — this is the early-exit guard."""
        assert sync_job._format_custom_field_value("boolean", None) == ""
        assert sync_job._format_custom_field_value("integer", None) == ""
        assert sync_job._format_custom_field_value("float", None) == ""

    def test_boolean_preserves_truthiness(self, sync_job):
        assert sync_job._format_custom_field_value("boolean", True) is True
        assert sync_job._format_custom_field_value("boolean", False) is False
        # String "yes" is truthy → True
        assert sync_job._format_custom_field_value("boolean", "yes") is True

    def test_integer_converts_string(self, sync_job):
        result = sync_job._format_custom_field_value("integer", "42")
        assert result == 42
        assert isinstance(result, int)

    def test_integer_invalid_falls_back_to_zero(self, sync_job):
        assert sync_job._format_custom_field_value("integer", "not-a-number") == 0

    def test_float_converts_string(self, sync_job):
        result = sync_job._format_custom_field_value("float", "3.14")
        assert abs(result - 3.14) < 1e-9
        assert isinstance(result, float)

    def test_monetary_converts_to_float(self, sync_job):
        assert abs(sync_job._format_custom_field_value("monetary", "99.99") - 99.99) < 1e-9

    def test_monetary_invalid_falls_back_to_zero(self, sync_job):
        assert sync_job._format_custom_field_value("monetary", "EUR") == 0.0

    def test_date_converts_to_unix_timestamp(self, sync_job):
        ts = sync_job._format_custom_field_value("date", "2024-03-15")
        assert isinstance(ts, int)
        assert ts > 0

    def test_date_invalid_returns_zero(self, sync_job):
        assert sync_job._format_custom_field_value("date", "not-a-date") == 0

    def test_string_passthrough(self, sync_job):
        assert sync_job._format_custom_field_value("string", "Hello") == "Hello"

    def test_url_passthrough(self, sync_job):
        assert sync_job._format_custom_field_value("url", "https://example.com") == "https://example.com"

    def test_documentlink_int_becomes_string(self, sync_job):
        """Document link IDs come as ints; they must be cast to str for ChromaDB."""
        assert sync_job._format_custom_field_value("documentlink", 5) == "5"


# ---------------------------------------------------------------------------
# _date_to_timestamp (sync_job variant uses fromisoformat, handles timezones)
# ---------------------------------------------------------------------------

class TestDateToTimestamp:
    def test_simple_date(self, sync_job):
        ts = sync_job._date_to_timestamp("2024-02-15")
        assert isinstance(ts, int) and ts > 0

    def test_iso_datetime_with_utc_timezone(self, sync_job):
        """Paperless often returns ISO datetimes with Z suffix."""
        ts = sync_job._date_to_timestamp("2024-02-15T12:00:00Z")
        assert isinstance(ts, int) and ts > 0

    def test_empty_string_returns_zero(self, sync_job):
        assert sync_job._date_to_timestamp("") == 0

    def test_invalid_returns_zero(self, sync_job):
        assert sync_job._date_to_timestamp("not-a-date") == 0
