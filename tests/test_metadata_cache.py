import pytest
from unittest.mock import AsyncMock, MagicMock
from semantic.metadata_cache import MetadataCache

@pytest.fixture
def cache():
    return MetadataCache(ttl_seconds=60)

@pytest.mark.asyncio
async def test_fetch_all_paginated(cache):
    client = MagicMock()
    client._get = AsyncMock()

    # Mock two pages of results
    client._get.side_effect = [
        {"results": [{"id": 1, "name": "Tag 1"}], "next": "page2"},
        {"results": [{"id": 2, "name": "Tag 2"}], "next": None}
    ]

    results = await cache._fetch_all_paginated(client, "tags/")

    assert len(results) == 2
    assert results[0]["name"] == "Tag 1"
    assert results[1]["name"] == "Tag 2"
    assert client._get.call_count == 2

@pytest.mark.asyncio
async def test_force_refresh(cache):
    client = MagicMock()
    client._get = AsyncMock()

    # Mock data for all endpoints
    # Correspondents, Document Types, Custom Fields, Tags
    client._get.side_effect = [
        {"results": [{"id": 1, "name": "Corr 1"}], "next": None},
        {"results": [{"id": 1, "name": "Type 1"}], "next": None},
        {"results": [{"id": 1, "name": "Field 1", "data_type": "string"}], "next": None},
        {"results": [{"id": 1, "name": "Child", "parent": 2}, {"id": 2, "name": "Parent"}], "next": None}
    ]

    await cache._force_refresh(client)

    assert cache.correspondents[1] == "Corr 1"
    assert cache.document_types[1] == "Type 1"
    assert cache.custom_fields[1]["name"] == "Field 1"
    assert cache.get_tag_path(1) == "Parent/Child"
    assert cache.get_tag_path(2) == "Parent"

def test_getters_safe_fallbacks(cache):
    # Setup some initial data
    cache.correspondents = {1: "Known"}
    cache.tags = {1: {"name": "Tag 1", "path": "Path/To/Tag 1"}}

    assert cache.get_correspondent_name(1) == "Known"
    assert cache.get_correspondent_name(99) == "Unknown Correspondent"

    assert cache.get_tag_name(1) == "Tag 1"
    assert cache.get_tag_name(99) == "Unknown Tag"

    assert cache.get_tag_path(1) == "Path/To/Tag 1"
    assert cache.get_tag_path(99) == "Unknown Tag"
