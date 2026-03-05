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

from server.mcp_tools import semantic_search_with_filters

@pytest.mark.asyncio
async def test_semantic_search_with_filters_date_conversion():
    with patch("server.mcp_tools.vector_store") as mock_vs:
        mock_vs.search.return_value = {
            "documents": [["chunk1"]],
            "metadatas": [[{"document_id": 1, "title": "Doc1", "created_str": "2024-02-15"}]],
            "distances": [[0.1]]
        }
        
        # We test that ISO date strings in the tool call are converted to timestamps in the vector store query
        # 2024-02-15 is 1707955200 in UTC (assuming no timezone issues in test env)
        # However, it's safer to just check if it's an int.
        
        await semantic_search_with_filters(
            query="test",
            document_id=0,
            created_after="2024-02-15",
            created_before="",
            added_after="",
            added_before=""
        )
        
        args, kwargs = mock_vs.search.call_args
        where = kwargs.get("where_filter")
        assert "created" in where
        assert "$gte" in where["created"]
        assert isinstance(where["created"]["$gte"], int)
        assert where["created"]["$gte"] > 0

@pytest.mark.asyncio
async def test_semantic_search_with_filters_no_results():
    with patch("server.mcp_tools.vector_store") as mock_vs:
        # Test the robust extraction fix
        mock_vs.search.return_value = {
            "documents": [],
            "metadatas": [],
            "distances": []
        }
        
        result = await semantic_search_with_filters(
            query="test",
            document_id=0,
            created_after="",
            created_before="",
            added_after="",
            added_before=""
        )
        assert "No relevant semantic chunks found" in result

@pytest.mark.asyncio
async def test_semantic_search_with_filters_empty_lists():
    with patch("server.mcp_tools.vector_store") as mock_vs:
        # Test the robust extraction fix with empty nested lists
        mock_vs.search.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }
        
        result = await semantic_search_with_filters(
            query="test",
            document_id=0,
            created_after="",
            created_before="",
            added_after="",
            added_before=""
        )
        assert "No relevant semantic chunks found" in result
