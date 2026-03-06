import asyncio
from fastapi import FastAPI, BackgroundTasks, Request, Response, status
from loguru import logger
from core.config import settings
from api.paperless_client import PaperlessAPIClient
from semantic.sync_job import SyncJob
from server.mcp_tools import mcp
import core.logger  # Ensure logger is set up

from contextlib import asynccontextmanager
from semantic.metadata_cache import metadata_cache

# Extract the MCP ASGI app into a variable so we can access its lifespan
mcp_asgi_app = mcp.streamable_http_app()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep our existing Paperless cache logic
    client = PaperlessAPIClient()
    try:
        await metadata_cache.refresh_if_needed(client)
    finally:
        await client.close()

    # Forward the lifespan to the mounted MCP app
    # This manually triggers FastMCP's startup events and initializes the task groups.
    async with mcp_asgi_app.router.lifespan_context(app):
        yield

# Initialize FastAPI App
app = FastAPI(
    title="paperless-mcp-server",
    description="Searchless-ngx: Agentic RAG and MCP server for Paperless-ngx",
    version="0.1.3",
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
