import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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

    assert cache.get_document_type_name(99) == "Unknown Type"
    assert cache.get_custom_field_name(99) == "Unknown Field"
    name, dtype = cache.get_custom_field_info(99)
    assert name == "Unknown Field"
    assert dtype == "string"


def _make_single_page_client():
    """Return a mock client that answers all metadata endpoints with one item each."""
    client = MagicMock()
    client._get = AsyncMock()
    client._get.side_effect = [
        {"results": [{"id": 1, "name": "Corr 1"}], "next": None},
        {"results": [{"id": 1, "name": "Type 1"}], "next": None},
        {"results": [{"id": 1, "name": "Field 1", "data_type": "string"}], "next": None},
        {"results": [{"id": 1, "name": "Tag 1"}], "next": None},
    ]
    return client


@pytest.mark.asyncio
async def test_refresh_if_needed_triggers_when_stale():
    """Cache with last_updated=0 (never refreshed) must call _force_refresh."""
    cache = MetadataCache(ttl_seconds=60)
    assert cache.last_updated == 0.0

    client = _make_single_page_client()
    await cache.refresh_if_needed(client)

    # After refresh the cache should be populated and last_updated set
    assert cache.last_updated > 0
    assert 1 in cache.correspondents


@pytest.mark.asyncio
async def test_refresh_if_needed_skips_when_fresh():
    """Cache that was just refreshed must NOT call _force_refresh again."""
    cache = MetadataCache(ttl_seconds=60)
    cache.last_updated = time.time()  # mark as just refreshed

    client = MagicMock()
    client._get = AsyncMock()

    await cache.refresh_if_needed(client)

    client._get.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_if_needed_triggers_after_ttl_expires():
    """Cache whose TTL has expired must call _force_refresh."""
    cache = MetadataCache(ttl_seconds=1)
    cache.last_updated = time.time() - 2  # expired 2 seconds ago

    client = _make_single_page_client()
    await cache.refresh_if_needed(client)

    assert cache.last_updated > 0
    assert 1 in cache.correspondents


@pytest.mark.asyncio
async def test_tag_hierarchy_deep_nesting():
    """Tags with 3-level hierarchy must be resolved to full path."""
    cache = MetadataCache()
    client = MagicMock()
    client._get = AsyncMock()
    client._get.side_effect = [
        {"results": [], "next": None},  # correspondents
        {"results": [], "next": None},  # document types
        {"results": [], "next": None},  # custom fields
        {
            "results": [
                {"id": 1, "name": "Root"},
                {"id": 2, "name": "Middle", "parent": 1},
                {"id": 3, "name": "Leaf", "parent": 2},
            ],
            "next": None,
        },
    ]
    await cache._force_refresh(client)

    assert cache.get_tag_path(3) == "Root/Middle/Leaf"
    assert cache.get_tag_path(2) == "Root/Middle"
    assert cache.get_tag_path(1) == "Root"
