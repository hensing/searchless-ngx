import time
import asyncio
from typing import Dict, Any, Tuple, List
from loguru import logger
from api.paperless_client import PaperlessAPIClient

class MetadataCache:
    """
    An in-memory cache for Paperless-ngx metadata.
    Refreshes automatically if the data is older than the specified TTL.
    """
    def __init__(self, ttl_seconds: int = 900):
        self.ttl_seconds = ttl_seconds
        self.last_updated = 0.0

        # In-memory dictionaries
        self.tags: Dict[int, Dict[str, Any]] = {}
        self.correspondents: Dict[int, str] = {}
        self.document_types: Dict[int, str] = {}
        self.custom_fields: Dict[int, Dict[str, Any]] = {}

        # Lock to prevent concurrent cache refreshes
        self._lock = asyncio.Lock()

    async def refresh_if_needed(self, client: PaperlessAPIClient):
        """Checks if the cache is stale and refreshes it if necessary."""
        if time.time() - self.last_updated > self.ttl_seconds:
            async with self._lock:
                # Double check inside the lock to avoid race conditions
                if time.time() - self.last_updated > self.ttl_seconds:
                    await self._force_refresh(client)

    async def _fetch_all_paginated(self, client: PaperlessAPIClient, endpoint: str) -> List[Dict[str, Any]]:
        """Helper to fetch all results from a paginated endpoint."""
        results = []
        page = 1
        while True:
            resp = await client._get(endpoint, params={"page": page, "page_size": 100})
            results.extend(resp.get("results", []))
            if not resp.get("next"):
                break
            page += 1
        return results

    async def _force_refresh(self, client: PaperlessAPIClient):
        """Forces a refresh of all metadata from the Paperless API."""
        logger.info("Refreshing in-memory Metadata Cache...")
        try:
            # 1. Fetch Correspondents (All pages)
            corrs = await self._fetch_all_paginated(client, "correspondents/")
            self.correspondents = {c["id"]: c["name"] for c in corrs}

            # 2. Fetch Document Types (All pages)
            document_types = await self._fetch_all_paginated(client, "document_types/")
            self.document_types = {dt["id"]: dt["name"] for dt in document_types}

            # 3. Fetch Custom Fields (All pages)
            custom_fields = await self._fetch_all_paginated(client, "custom_fields/")
            self.custom_fields = {
                cf["id"]: {"name": cf["name"], "data_type": cf["data_type"]}
                for cf in custom_fields
            }

            # 4. Fetch Tags (and resolve hierarchies) (All pages)
            raw_tags = await self._fetch_all_paginated(client, "tags/")

            # First pass: map raw tags
            tag_map = {t["id"]: t for t in raw_tags}

            # Second pass: resolve full paths
            resolved_tags = {}
            for t in raw_tags:
                path = []
                current = t
                # Walk up the parent chain
                while current:
                    path.insert(0, current["name"])
                    parent_id = current.get("parent")
                    current = tag_map.get(parent_id) if parent_id else None

                resolved_tags[t["id"]] = {
                    "name": t["name"],
                    "path": "/".join(path)
                }
            self.tags = resolved_tags

            self.last_updated = time.time()
            logger.info("Metadata Cache refresh complete.")
        except Exception as e:
            logger.error(f"Failed to refresh Metadata Cache: {e}")

    # --- Resolution Helpers ---

    def get_correspondent_name(self, id_val: int) -> str:
        return self.correspondents.get(id_val, "Unknown Correspondent")

    def get_document_type_name(self, id_val: int) -> str:
        return self.document_types.get(id_val, "Unknown Type")

    def get_tag_name(self, id_val: int) -> str:
        tag_info = self.tags.get(id_val)
        return tag_info["name"] if tag_info else "Unknown Tag"

    def get_tag_path(self, id_val: int) -> str:
        """Returns the fully resolved hierarchical path, e.g., 'Finance/Invoice'"""
        tag_info = self.tags.get(id_val)
        return tag_info["path"] if tag_info else "Unknown Tag"

    def get_custom_field_name(self, id_val: int) -> str:
        cf_info = self.custom_fields.get(id_val)
        return cf_info["name"] if cf_info else "Unknown Field"

    def get_custom_field_info(self, id_val: int) -> Tuple[str, str]:
        """Returns a tuple of (Field Name, Data Type)."""
        cf_info = self.custom_fields.get(id_val)
        if cf_info:
            return cf_info["name"], cf_info["data_type"]
        return "Unknown Field", "string"

# Global singleton instance
metadata_cache = MetadataCache()
