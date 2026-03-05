import pytest
from semantic.sync_job import SyncJob
from api.paperless_client import PaperlessAPIClient

@pytest.fixture
def sync_job(paperless_client: PaperlessAPIClient):
    return SyncJob(client=paperless_client)

def test_sync_job_chunk_text(sync_job: SyncJob):
    """Test character-based chunking logic."""
    long_text = "a" * 2500
    chunks = sync_job._chunk_text(long_text)

    # 2500 total, chunk_size=1000, overlap=200
    # chunk 1: 0-1000
    # chunk 2: 800-1800
    # chunk 3: 1600-2500
    assert len(chunks) == 3
    assert len(chunks[0]) == 1000
    assert len(chunks[1]) == 1000
    assert len(chunks[2]) == 900

def test_vector_store_add_chunks(mock_vector_store):
    """Test adding chunks to ChromaDB and verify metadata gets attached properly."""
    mock_vector_store._ensure_initialized()

    document_id = 99
    chunks = ["Chunk 1 text", "Chunk 2 text"]
    chunk_ids = ["doc_99_chunk_0", "doc_99_chunk_1"]
    metadatas = [
        {"document_id": document_id, "title": "Test Doc", "tags": "Finance/Invoice", "document_type": "Receipt", "correspondent": "Amazon", "created": "2023-01-01", "modified": "2023-01-02", "cf_invoice_total": 150.5},
        {"document_id": document_id, "title": "Test Doc", "tags": "Finance/Invoice", "document_type": "Receipt", "correspondent": "Amazon", "created": "2023-01-01", "modified": "2023-01-02", "cf_invoice_total": 150.5}
    ]

    # Add chunks
    mock_vector_store.add_chunks(
        document_id=document_id,
        chunks=chunks,
        chunk_ids=chunk_ids,
        metadatas=metadatas
    )

    # Query back to verify using our wrapper (using the metadata filter)
    results = mock_vector_store.search("Chunk 1 text", n_results=5, where_filter={"document_id": document_id})

    assert "documents" in results
    # Since we are using an ephemeral mock embedding function (which just does hash/length or exact match),
    # results should reflect what we added.
    returned_docs = results["documents"][0]
    assert len(returned_docs) == 2
    assert "Chunk 1 text" in returned_docs or "Chunk 2 text" in returned_docs

    returned_metas = results["metadatas"][0]
    assert returned_metas[0]["document_id"] == 99
    assert returned_metas[0]["tags"] == "Finance/Invoice"
    assert returned_metas[0]["correspondent"] == "Amazon"
    assert returned_metas[0]["cf_invoice_total"] == 150.5
    assert returned_metas[0]["modified"] == "2023-01-02"

@pytest.mark.asyncio
async def test_lifecycle_management_skip_unmodified(mock_vector_store, sync_job, monkeypatch):
    """Test that syncing skips re-embedding if the modified timestamp hasn't changed."""
    # Pre-populate ChromaDB with a specific modified date
    mock_vector_store.add_chunks(
        document_id=50,
        chunks=["Old content"],
        chunk_ids=["doc_50_0"],
        metadatas=[{"document_id": 50, "modified": "2023-10-10T10:00:00Z"}]
    )

    # Mock the API client to return the SAME modified date
    mock_doc = {
        "id": 50,
        "content": "New content but same modified date?!",
        "modified": "2023-10-10T10:00:00Z"
    }

    async def mock_get_doc(*args, **kwargs):
        return mock_doc

    async def mock_refresh(*args, **kwargs):
        pass

    async def mock_get_notes(*args, **kwargs):
        return []

    monkeypatch.setattr(sync_job.client, "get_document", mock_get_doc)
    monkeypatch.setattr("semantic.sync_job.metadata_cache.refresh_if_needed", mock_refresh)
    monkeypatch.setattr(sync_job.client, "get_document_notes", mock_get_notes)

    # Track calls manually
    add_chunks_called = False

    # We must patch the global vector_store used in sync_job
    import semantic.sync_job
    original_add_chunks = semantic.sync_job.vector_store.add_chunks

    def mock_add_chunks(*args, **kwargs):
        nonlocal add_chunks_called
        add_chunks_called = True
        return original_add_chunks(*args, **kwargs)

    monkeypatch.setattr(semantic.sync_job.vector_store, "add_chunks", mock_add_chunks)

    await sync_job.sync_document(50)

    assert not add_chunks_called

    # Now change the modified date and test it updates
    mock_doc["modified"] = "2023-10-11T10:00:00Z"

    await sync_job.sync_document(50)

    assert add_chunks_called


def test_vector_store_delete_document(mock_vector_store):
    """Test deleting vector chunks for an orphaned document."""
    mock_vector_store._ensure_initialized()

    # Insert some dummy data
    mock_vector_store.add_chunks(
        document_id=100,
        chunks=["Delete me"],
        chunk_ids=["doc_100_0"],
        metadatas=[{"document_id": 100}]
    )

    # Verify it exists
    results = mock_vector_store.search("Delete me", where_filter={"document_id": 100})
    assert len(results["documents"][0]) == 1

    # Delete it
    mock_vector_store.delete_document(100)

    # Verify it's gone
    results2 = mock_vector_store.search("Delete me", where_filter={"document_id": 100})
    assert len(results2["documents"][0]) == 0
