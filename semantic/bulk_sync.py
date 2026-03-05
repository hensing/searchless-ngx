import asyncio
import sys
from loguru import logger
from api.paperless_client import PaperlessAPIClient
from semantic.sync_job import SyncJob
from semantic.vector_store import vector_store

async def bulk_sync_documents():
    """
    Performs a bulk ingestion of all documents from Paperless-ngx into the Vector Store.
    Uses pagination and concurrency limits to avoid overwhelming the APIs.
    """
    # Ensure VectorStore is initialized
    vector_store._ensure_initialized()

    client = PaperlessAPIClient()
    job = SyncJob(client)

    # Configuration
    PAGE_SIZE = 50
    CONCURRENCY_LIMIT = 5
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    from core.config import settings

    try:
        logger.info("Starting Bulk Sync Job...")

        limit = settings.bulk_sync_limit
        base_params = {"ordering": "-added"} # Order by newest first

        # 1. Fetch the first page to get total count
        params = {**base_params, "page": 1, "page_size": PAGE_SIZE}
        first_page = await client.get_documents(params=params)
        total_count = first_page.get("count", 0)

        if total_count == 0:
            logger.info("No documents found in Paperless-ngx. Aborting bulk sync.")
            return

        if limit and limit < total_count:
            logger.info(f"BULK_SYNC_LIMIT is set to {limit}. Limiting sync to the {limit} newest documents.")
            total_count = limit

        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
        logger.info(f"Discovered {total_count} documents to sync. Processing across {total_pages} pages (Batch size: {PAGE_SIZE}).")

        processed_count = 0

        async def process_document_safe(doc_id: int):
            """Process a single document with concurrency limits and resilience."""
            async with semaphore:
                try:
                    await job.sync_document(doc_id)
                except Exception as e:
                    logger.error(f"Failed to sync document {doc_id} during bulk sync: {e}")

        # 2. Iterate through all pages
        for page in range(1, total_pages + 1):
            logger.info(f"Fetching page {page}/{total_pages}...")

            page_params = {**base_params, "page": page, "page_size": PAGE_SIZE}
            response = await client.get_documents(params=page_params)
            documents = response.get("results", [])

            if not documents:
                break

            # 3. Process the batch
            # Respect the global limit constraint mid-batch
            remaining = total_count - processed_count
            if remaining < len(documents):
                documents = documents[:remaining]

            tasks = [process_document_safe(doc.get("id")) for doc in documents if doc.get("id")]
            await asyncio.gather(*tasks)

            processed_count += len(tasks)
            logger.info(f"[INFO] Processed batch {page}/{total_pages} ({processed_count}/{total_count} documents)...")

            if processed_count >= total_count:
                break

        logger.info(f"Bulk sync completed successfully! Processed {processed_count} documents.")

    except Exception as e:
        logger.error(f"Fatal error during bulk sync: {e}")
        sys.exit(1)
    finally:
        await client.close()

if __name__ == "__main__":
    # Setup loguru (if not already set globally)
    # The core.logger initializes it, but we import it to ensure settings take effect
    import core.logger

    asyncio.run(bulk_sync_documents())
