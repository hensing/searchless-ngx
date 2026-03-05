import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from server.mcp_tools import search_paperless_metadata

@pytest.mark.asyncio
async def test_search_paperless_metadata_empty_query():
    # Mock dependencies
    with patch("server.mcp_tools.client") as mock_client, \
         patch("server.mcp_tools.metadata_cache") as mock_cache, \
         patch("server.mcp_tools.settings") as mock_settings:
        
        mock_settings.public_url = "http://paperless.test"
        mock_cache.refresh_if_needed = AsyncMock()
        mock_cache.get_correspondent_name.return_value = "Test Corr"
        mock_cache.get_tag_path.return_value = "Test/Tag"
        
        mock_client.get_documents = AsyncMock(return_value={
            "results": [
                {
                    "id": 1,
                    "title": "Test Doc",
                    "correspondent": 1,
                    "tags": [1],
                    "created": "2024-01-01",
                    "modified": "2024-01-01",
                    "content": "Sample content"
                }
            ]
        })
        
        # Call with empty query, providing defaults because we call directly (bypassing FastMCP injection)
        result = await search_paperless_metadata(
            query="",
            page_size=5,
            tags="",
            correspondent=0,
            document_type=0,
            created_after="",
            created_before=""
        )
        
        # Verify params sent to API (should not include query)
        args, kwargs = mock_client.get_documents.call_args
        params = kwargs.get("params", {})
        assert "query" not in params
        assert params["ordering"] == "-created"
        
        # Verify output formatting
        assert "Test Doc" in result
        assert "Test Corr" in result
        assert "### 📄 [Test Doc (ID: 1)]" in result
        assert "http://paperless.test/documents/1/details" in result

@pytest.mark.asyncio
async def test_search_paperless_metadata_with_query():
    with patch("server.mcp_tools.client") as mock_client, \
         patch("server.mcp_tools.metadata_cache") as mock_cache:
        
        mock_cache.refresh_if_needed = AsyncMock()
        mock_client.get_documents = AsyncMock(return_value={"results": []})
        
        await search_paperless_metadata(
            query="invoice",
            page_size=5,
            tags="",
            correspondent=0,
            document_type=0,
            created_after="",
            created_before=""
        )
        
        args, kwargs = mock_client.get_documents.call_args
        params = kwargs.get("params", {})
        assert params["query"] == "invoice"
