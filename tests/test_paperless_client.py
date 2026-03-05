import pytest
import respx
import httpx
from httpx import Response
from api.paperless_client import PaperlessAPIClient

@pytest.mark.asyncio
@respx.mock
async def test_get_documents_success(paperless_client: PaperlessAPIClient):
    """Test successful fetching of documents."""
    mock_response = {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [{"id": 1, "title": "Test Doc"}]
    }
    respx.get("http://mock-paperless/api/documents/").mock(return_value=Response(200, json=mock_response))

    result = await paperless_client.get_documents()
    assert result == mock_response

    await paperless_client.close()

@pytest.mark.asyncio
@respx.mock
async def test_get_document_content_success(paperless_client: PaperlessAPIClient):
    """Test successful fetching of document content."""
    mock_response = {"id": 1, "content": "This is mock OCR text."}
    respx.get("http://mock-paperless/api/documents/1/").mock(return_value=Response(200, json=mock_response))

    result = await paperless_client.get_document(1)
    assert result["content"] == "This is mock OCR text."

    await paperless_client.close()

@pytest.mark.asyncio
@respx.mock
async def test_get_document_notes_success(paperless_client: PaperlessAPIClient):
    """Test successful fetching of document notes."""
    mock_response = [{"id": 1, "note": "A note", "user": 1}]
    # Handle list response directly as per the code handling both list and dict formats
    respx.get("http://mock-paperless/api/documents/1/notes/").mock(return_value=Response(200, json=mock_response))

    result = await paperless_client.get_document_notes(1)
    assert len(result) == 1
    assert result[0]["note"] == "A note"

    await paperless_client.close()

@pytest.mark.asyncio
@respx.mock
async def test_retry_on_429(paperless_client: PaperlessAPIClient, monkeypatch):
    """Test that tenacity retries on 429 Too Many Requests, and eventually succeeds."""
    mock_response_success = {"id": 1, "title": "Success after retry"}

    route = respx.get("http://mock-paperless/api/documents/1/")
    route.side_effect = [
        Response(429, json={"detail": "Too Many Requests"}),
        Response(429, json={"detail": "Too Many Requests"}),
        Response(200, json=mock_response_success)
    ]

    # We should patch sleep in tenacity so the test runs instantly instead of waiting for exponential backoff
    async def mock_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", mock_sleep)
    monkeypatch.setattr("tenacity.nap.time.sleep", mock_sleep)

    result = await paperless_client.get_document(1)
    assert result == mock_response_success
    assert route.call_count == 3

    await paperless_client.close()

@pytest.mark.asyncio
@respx.mock
async def test_retry_failure(paperless_client: PaperlessAPIClient, monkeypatch):
    """Test that after max retries it actually raises the exception."""
    route = respx.get("http://mock-paperless/api/documents/1/")
    route.side_effect = [Response(429)] * 6  # Return 429 endlessly

    async def mock_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", mock_sleep)

    with pytest.raises(httpx.HTTPStatusError):
        await paperless_client.get_document(1)

    await paperless_client.close()
