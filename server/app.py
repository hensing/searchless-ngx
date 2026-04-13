import asyncio
from datetime import datetime, timedelta
from importlib.metadata import version, PackageNotFoundError
from fastapi import FastAPI, BackgroundTasks, Query, Request, Response, status
from loguru import logger
from core.config import settings
from api.paperless_client import PaperlessAPIClient
from semantic.sync_job import SyncJob  # used by process_sync (webhook handler)
from semantic.bulk_sync import bulk_sync_documents
from server.mcp_tools import mcp
import core.logger  # Ensure logger is set up

from contextlib import asynccontextmanager
from semantic.metadata_cache import metadata_cache

try:
    __version__ = version("paperless-mcp-server")
except PackageNotFoundError:
    __version__ = "dev"

async def _periodic_sync_loop(interval_minutes: int):
    """Runs bulk_sync_documents() every interval_minutes minutes."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        next_run = datetime.now() + timedelta(minutes=interval_minutes)
        logger.info(f"Periodic sync starting (interval: {interval_minutes} min) ...")
        await bulk_sync_documents(force=False)
        logger.info(
            f"Periodic sync done. Next run at {next_run.strftime('%H:%M')} "
            f"(in {interval_minutes} min)."
        )


# Extract the MCP ASGI app into a variable so we can access its lifespan
mcp_asgi_app = mcp.streamable_http_app()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refresh metadata cache on startup
    client = PaperlessAPIClient()
    try:
        await metadata_cache.refresh_if_needed(client)
    finally:
        await client.close()

    # Forward the lifespan to the mounted MCP app
    async with mcp_asgi_app.router.lifespan_context(app):
        logger.info("━" * 60)
        logger.info(f"  Searchless-ngx  ·  Search less, find more.  (v{__version__})")
        logger.info("  Agentic RAG + MCP server for Paperless-ngx")
        logger.info("  github.com/hensing/paperless-mcp-agent")
        logger.info("━" * 60)
        asyncio.create_task(bulk_sync_documents(force=False))
        logger.info("Startup sync scheduled — watching for new and changed documents.")
        if settings.sync_interval_minutes > 0:
            asyncio.create_task(_periodic_sync_loop(settings.sync_interval_minutes))
            next_run = datetime.now() + timedelta(minutes=settings.sync_interval_minutes)
            logger.info(
                f"Periodic sync enabled — every {settings.sync_interval_minutes} min. "
                f"Next run at {next_run.strftime('%H:%M')}."
            )
        yield

# Initialize FastAPI App
app = FastAPI(
    title="paperless-mcp-server",
    description="Searchless-ngx: Agentic RAG and MCP server for Paperless-ngx",
    version=__version__,
    lifespan=lifespan
)

# Background processing logic
async def process_sync(payload: dict):
    logger.info(f"Processing webhook payload: {payload}")

    # Paperless Webhook structure typically contains a document ID
    # and possibly the event type.
    document_id = payload.get("document_id")
    event_type = payload.get("event", "updated")  # assumed structure, needs tuning based on exact paperless version

    if not document_id:
        logger.warning("No document_id found in webhook payload.")
        return

    # In a real background task, you want a fresh client context or a global one
    client = PaperlessAPIClient()
    try:
        job = SyncJob(client)

        if event_type == "deleted":
            await job.delete_document(document_id)
        else:
            # Handles both added and updated
            await job.sync_document(document_id)

    except Exception as e:
        logger.error(f"Error in background sync for document {document_id}: {e}")
    finally:
        await client.close()


@app.post("/sync/all", status_code=status.HTTP_202_ACCEPTED)
async def sync_all(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False, description="Re-sync even unmodified documents"),
):
    """
    Trigger a full sync of all Paperless-ngx documents into ChromaDB.
    Runs in the background; returns immediately. Respects BULK_SYNC_LIMIT env var.
    Use ?force=true to re-embed already-synced documents.
    """
    background_tasks.add_task(bulk_sync_documents, force)
    limit_note = f", capped at BULK_SYNC_LIMIT={settings.bulk_sync_limit}" if settings.bulk_sync_limit else ""
    return {"message": f"Full sync started{limit_note}. Watch server logs for progress."}


@app.get("/sync/status")
async def sync_status():
    """Returns the number of documents in Paperless vs. chunks in ChromaDB."""
    from semantic.vector_store import vector_store
    vector_store._ensure_initialized()
    chroma_chunks = vector_store.collection.count() if vector_store.collection else 0

    client = PaperlessAPIClient()
    try:
        response = await client.get_documents(params={"page_size": 1})
        paperless_docs = response.get("count", 0)
    finally:
        await client.close()

    return {
        "paperless_documents": paperless_docs,
        "chroma_chunks": chroma_chunks,
        "bulk_sync_limit": settings.bulk_sync_limit,
    }


@app.post("/webhook/sync", status_code=status.HTTP_202_ACCEPTED)
async def webhook_sync(request: Request, background_tasks: BackgroundTasks):
    """
    Receives Webhook events from Paperless-ngx.
    Returns 202 immediately to avoid blocking the Paperless instance.
    """
    try:
        # Depending on how Paperless sends the webhook (JSON or Form)
        payload = await request.json()
    except Exception:
        # Fallback if empty or not JSON
        payload = {}

    # Offload the processing
    background_tasks.add_task(process_sync, payload)

    return {"message": "Sync job accepted"}

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "paperless-mcp-server"}

@app.get("/test-connection")
async def test_connection():
    """
    Actively test the connection to Paperless-ngx API and ChromaDB.
    Returns 200 if everything is configured correctly.
    """
    client = PaperlessAPIClient()
    try:
        # Test Paperless API
        # We fetch 1 document just to verify token and URL
        response = await client._get("documents/", params={"page_size": 1})
        paperless_ok = "results" in response

        # Test VectorStore (ChromaDB)
        from semantic.vector_store import vector_store
        vector_store._ensure_initialized()
        chroma_ok = vector_store.collection is not None

        return {
            "status": "success",
            "paperless_connected": paperless_ok,
            "vector_store_initialized": chroma_ok
        }
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return Response(content=f"Connection test failed: {e}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        await client.close()

# Mount the FastMCP streamable HTTP app at the root.
# Explicit routes defined above take precedence.
app.mount("/", mcp_asgi_app)
