"""
Tests for non-trivial MCP tool logic:
- _resolve_time_range: complex date arithmetic with wrap-around edge cases
- get_document_details: conditional output sections
- semantic_search_with_filters + time_range: end-to-end pipeline
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from server.mcp_tools import _resolve_time_range

FROZEN_DATE = datetime(2024, 7, 15)  # mid-Q3, used for all relative date tests


@pytest.fixture
def frozen_today():
    """Pin datetime.now() inside mcp_tools to a fixed date."""
    mock_dt = MagicMock(wraps=datetime)
    mock_dt.now.return_value = FROZEN_DATE
    mock_dt.strptime = datetime.strptime
    mock_dt.fromisoformat = datetime.fromisoformat
    with patch("server.mcp_tools.datetime", mock_dt):
        yield


# ---------------------------------------------------------------------------
# _resolve_time_range — pure date-math, no mocking needed for explicit year
# ---------------------------------------------------------------------------

class TestResolveTimeRange:
    def test_empty_string_returns_empty_pair(self):
        assert _resolve_time_range("") == ("", "")

    def test_unrecognized_expression_returns_empty_pair(self):
        assert _resolve_time_range("whenever") == ("", "")

    def test_explicit_year(self):
        assert _resolve_time_range("2024") == ("2024-01-01", "2024-12-31")
        assert _resolve_time_range("2019") == ("2019-01-01", "2019-12-31")

    def test_last_year(self, frozen_today):
        assert _resolve_time_range("last year") == ("2023-01-01", "2023-12-31")

    def test_last_year_german(self, frozen_today):
        assert _resolve_time_range("letztes jahr") == ("2023-01-01", "2023-12-31")

    def test_this_year(self, frozen_today):
        after, before = _resolve_time_range("this year")
        assert after == "2024-01-01"
        assert before == "2024-07-15"  # capped at today

    def test_this_year_german(self, frozen_today):
        after, before = _resolve_time_range("dieses jahr")
        assert after == "2024-01-01"
        assert before == "2024-07-15"

    def test_last_month(self, frozen_today):
        # July 2024 → June 2024 (30 days)
        assert _resolve_time_range("last month") == ("2024-06-01", "2024-06-30")

    def test_last_month_january_wraparound(self):
        """January → last month must be December of the previous year."""
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now.return_value = datetime(2024, 1, 10)
        mock_dt.strptime = datetime.strptime
        with patch("server.mcp_tools.datetime", mock_dt):
            assert _resolve_time_range("last month") == ("2023-12-01", "2023-12-31")

    def test_this_month(self, frozen_today):
        after, before = _resolve_time_range("this month")
        assert after == "2024-07-01"
        assert before == "2024-07-15"

    def test_last_quarter(self, frozen_today):
        # Q3 2024 (July) → last quarter is Q2: Apr–Jun
        assert _resolve_time_range("last quarter") == ("2024-04-01", "2024-06-30")

    def test_last_quarter_german(self, frozen_today):
        assert _resolve_time_range("letztes quartal") == ("2024-04-01", "2024-06-30")

    def test_last_quarter_q1_wraparound(self):
        """Q1 → last quarter must be Q4 of the previous year."""
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now.return_value = datetime(2024, 2, 20)
        mock_dt.strptime = datetime.strptime
        with patch("server.mcp_tools.datetime", mock_dt):
            assert _resolve_time_range("last quarter") == ("2023-10-01", "2023-12-31")

    def test_whitespace_and_uppercase(self, frozen_today):
        assert _resolve_time_range("  LAST YEAR  ") == ("2023-01-01", "2023-12-31")


# ---------------------------------------------------------------------------
# get_document_details — conditional output sections
# The function has three optional blocks depending on whether the document
# has tags, custom fields, and notes. These branches are what we test here.
# ---------------------------------------------------------------------------

from server.mcp_tools import get_document_details


def _make_mock_document(*, tags=None, custom_fields=None, content="OCR text"):
    """Build a minimal mock document dict."""
    return {
        "id": 1,
        "title": "Test Doc",
        "correspondent": None,
        "document_type": None,
        "tags": tags or [],
        "created": "2024-01-01",
        "content": content,
        "custom_fields": custom_fields or [],
    }


@pytest.mark.asyncio
async def test_get_document_details_includes_all_sections():
    """Full document: tags, custom fields, and notes must all appear in output."""
    with patch("server.mcp_tools.client") as mock_client, \
         patch("server.mcp_tools.metadata_cache") as mock_cache, \
         patch("server.mcp_tools.settings") as mock_settings:

        mock_settings.public_url = "http://paperless.test"
        mock_client.get_document = AsyncMock(return_value=_make_mock_document(
            tags=[1],
            custom_fields=[{"field": 10, "value": "49.90"}],
        ))
        mock_client.get_document_notes = AsyncMock(return_value=[
            {"created": "2024-01-02", "note": "Reviewed"}
        ])
        mock_cache.get_tag_path.return_value = "Finance/Invoice"
        mock_cache.get_custom_field_name.return_value = "Betrag"
        mock_cache.get_correspondent_name.return_value = "Unknown"
        mock_cache.get_document_type_name.return_value = "Unknown"

        result = await get_document_details(document_id=1)

        assert "Finance/Invoice" in result
        assert "Betrag" in result
        assert "49.90" in result
        assert "Reviewed" in result
        assert "User Notes" in result


@pytest.mark.asyncio
async def test_get_document_details_omits_optional_sections_when_absent():
    """Document with no tags, no custom fields, no notes must not render those sections."""
    with patch("server.mcp_tools.client") as mock_client, \
         patch("server.mcp_tools.metadata_cache") as mock_cache, \
         patch("server.mcp_tools.settings") as mock_settings:

        mock_settings.public_url = "http://paperless.test"
        mock_client.get_document = AsyncMock(return_value=_make_mock_document())
        mock_client.get_document_notes = AsyncMock(return_value=[])
        mock_cache.get_correspondent_name.return_value = "Unknown"
        mock_cache.get_document_type_name.return_value = "Unknown"

        result = await get_document_details(document_id=1)

        assert "Tags" not in result
        assert "Custom Fields" not in result
        assert "User Notes" not in result
        assert "OCR text" in result


# ---------------------------------------------------------------------------
# semantic_search_with_filters + time_range integration
# Verifies the full pipeline: time_range string → _resolve_time_range →
# _date_to_timestamp → ChromaDB $and filter.
# ---------------------------------------------------------------------------

from server.mcp_tools import semantic_search_with_filters


@pytest.mark.asyncio
async def test_semantic_search_time_range_builds_correct_chroma_filter():
    """
    time_range="2024" must produce a $and filter with both $gte (Jan 1) and $lte (Dec 31)
    as Unix timestamps. This tests the _resolve_time_range → _date_to_timestamp pipeline.
    """
    with patch("server.mcp_tools.vector_store") as mock_vs:
        mock_vs.search.return_value = {"documents": [], "metadatas": [], "distances": []}

        await semantic_search_with_filters(
            query="invoices",
            n_results=5,
            time_range="2024",
            document_id=0,
            created_after="",
            created_before="",
            added_after="",
            added_before="",
        )

        _, kwargs = mock_vs.search.call_args
        where = kwargs.get("where_filter")

        # Must have produced an $and condition (both start and end date)
        assert where is not None
        assert "$and" in where
        conditions = where["$and"]

        created_conditions = [c for c in conditions if "created" in c]
        assert len(created_conditions) == 2

        ops = {list(c["created"].keys())[0]: c["created"][list(c["created"].keys())[0]]
               for c in created_conditions}
        assert "$gte" in ops
        assert "$lte" in ops
        assert isinstance(ops["$gte"], int) and ops["$gte"] > 0
        assert isinstance(ops["$lte"], int) and ops["$lte"] > ops["$gte"]
