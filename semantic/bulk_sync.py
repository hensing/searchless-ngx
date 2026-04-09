import asyncio
import sys
from typing import List, Dict, Any, Optional
from loguru import logger
from api.paperless_client import PaperlessAPIClient
from semantic.sync_job import SyncJob
from semantic.vector_store import vector_store


async def _fetch_pages(
    client: PaperlessAPIClient,
    params: Dict[str, Any],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Paginate through Paperless API and return all matching document dicts."""
    docs: List[Dict] = []
    page = 1
    PAGE_SIZE = 100
    while True:
        response = await client.get_documents(params={**params, "page": page, "page_size": PAGE_SIZE})
        results = response.get("results", [])
        docs.extend(results)
        if limit and len(docs) >= limit:
            return docs[:limit]
        if not results or not response.get("next"):
            break
        page += 1
    return docs


async def _fetch_all_paperless_ids(client: PaperlessAPIClient) -> set:
    """
    Fetch all document IDs from Paperless for the deletion check.
    Only extracts IDs — no Gemini calls, no heavy processing.
    """
    ids: set = set()
    total: Optional[int] = None
    page = 1
    PAGE_SIZE = 250
    while True:
        response = await client.get_documents(params={"page": page, "page_size": PAGE_SIZE, "ordering": "id"})
        if total is None:
            total = response.get("count", 0)
        for doc in response.get("results", []):
            if "id" in doc:
                ids.add(doc["id"])
        if total and total > PAGE_SIZE:
            logger.info(f"Scanning Paperless ({len(ids)}/{total})...")
        if not response.get("next"):
            break
        page += 1
    return ids


async def bulk_sync_documents(force: bool = False):
    """
    Smart bulk sync of Paperless documents into ChromaDB.

    Incremental mode (default):
      1. Scan ChromaDB once → watermark (latest added_str), all doc IDs, incomplete set
      2. Ask Paperless for docs added OR modified since watermark (2 parallel API calls)
      3. ID-diff ChromaDB vs all Paperless IDs → deletions
      4. Gemini embeddings only for actually new/changed/incomplete docs

    Force mode (force=True or empty ChromaDB):
      Fetches all Paperless docs, compares modified timestamps, syncs only what changed.
    """
    vector_store._ensure_initialized()

    client = PaperlessAPIClient()
    job = SyncJob(client)

    CONCURRENCY_LIMIT = 5
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    from core.config import settings

    try:
        logger.info("Bulk sync starting...")

        # ── Step 1: Single ChromaDB scan (no Gemini) ──────────────────────────
        chroma = vector_store.scan_chroma_state()
        chroma_ids: set = chroma["chroma_ids"]
        latest_added_str: Optional[str] = chroma["latest_added_str"]
        incomplete_ids: set = chroma["incomplete_ids"]
        doc_modified: Dict[int, str] = chroma["doc_modified"]

        # ── Step 2: Determine what to sync ────────────────────────────────────
        if force or not latest_added_str:
            # Full delta: fetch all Paperless docs, compare modified timestamps
            mode = "force" if force else "initial (ChromaDB empty)"
            logger.info(f"Full sync ({mode}): fetching all Paperless documents...")

            limit = settings.bulk_sync_limit
            if limit:
                logger.info(f"BULK_SYNC_LIMIT={limit} — capping fetch to {limit} newest documents.")
            all_docs = await _fetch_pages(client, {"ordering": "-added"}, limit=limit)
            if not all_docs:
                logger.info("No documents in Paperless. Nothing to sync.")
                return

            paperless_id_set = {doc["id"] for doc in all_docs if "id" in doc}
            to_sync = [
                doc for doc in all_docs
                if (doc_id := doc.get("id")) is not None
                and (
                    doc_id not in doc_modified
                    or doc_modified[doc_id] != doc.get("modified", "")
                )
            ]
            to_delete = chroma_ids - paperless_id_set

        else:
            # Incremental: only fetch docs added or modified since watermark
            since = latest_added_str[:10]  # YYYY-MM-DD
            logger.info(f"Incremental sync since {since}...")

            # Two cheap filtered Paperless queries in parallel (no Gemini)
            new_docs, modified_docs = await asyncio.gather(
                _fetch_pages(client, {"added__date__gt": since, "ordering": "added"}),
                _fetch_pages(client, {"modified__date__gt": since, "ordering": "modified"}),
            )
            # Union by ID
            to_sync_map = {doc["id"]: doc for doc in new_docs + modified_docs if "id" in doc}
            to_sync = list(to_sync_map.values())

            # ID diff for deleted docs (lightweight: only extracts IDs)
            all_paperless_ids = await _fetch_all_paperless_ids(client)
            to_delete = chroma_ids - all_paperless_ids

        # Incomplete docs not already in to_sync and not being deleted
        to_sync_ids = {doc["id"] for doc in to_sync}
        force_ids = incomplete_ids - to_sync_ids - to_delete

        logger.info(
            f"Delta: {len(to_sync)} to sync, "
            f"{len(to_delete)} to delete, "
            f"{len(force_ids)} incomplete (force re-sync)."
        )

        # ── Step 3: Delete orphans ─────────────────────────────────────────────
        if to_delete:
            logger.info(f"Deleting {len(to_delete)} orphaned documents...")
            for doc_id in to_delete:
                await job.delete_document(doc_id)

        # ── Step 4: Sync (Gemini embeddings only here) ────────────────────────
        total = len(to_sync) + len(force_ids)
        if total == 0:
            logger.info("All documents are up to date.")
            return

        logger.info(f"Syncing {total} documents...")

        processed = 0

        async def sync_safe(doc_id: int, force_embed: bool = False):
            nonlocal processed
            async with semaphore:
                try:
                    await job.sync_document(doc_id, force=force_embed)
                    processed += 1
                    if processed % 250 == 0:
                        logger.info(f"Progress: {processed}/{total} synced.")
                except Exception as e:
                    logger.error(f"Failed to sync document {doc_id}: {e}")

        tasks = [sync_safe(doc["id"]) for doc in to_sync]
        tasks += [sync_safe(doc_id, force_embed=True) for doc_id in force_ids]
        await asyncio.gather(*tasks)

        logger.info(
            f"Bulk sync complete: {processed}/{total} synced, "
            f"{len(to_delete)} orphans deleted."
        )

    except Exception as e:
        logger.error(f"Fatal error during bulk sync: {e}")
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    import core.logger
    asyncio.run(bulk_sync_documents())
