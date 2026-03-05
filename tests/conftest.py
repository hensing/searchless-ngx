import pytest
import chromadb
from unittest.mock import patch
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

@pytest.fixture(autouse=True)
def mock_config():
    """Mock configuration for all tests so we don't accidentally load real env variables."""
    with patch("core.config.settings.paperless_url", "http://mock-paperless"):
        with patch("core.config.settings.paperless_token", "mock-token"):
            with patch("core.config.settings.gemini_api_key", "mock-gemini-key"):
                yield

@pytest.fixture
def mock_vector_store():
    """
    Creates an Ephemeral ChromaDB client for testing.
    Replaces the HTTP client in vector_store module.
    """
    with patch("semantic.vector_store.chromadb.HttpClient", return_value=chromadb.EphemeralClient()):
        with patch("semantic.vector_store.GeminiEmbeddingFunction", return_value=DefaultEmbeddingFunction()):
            from semantic.vector_store import VectorStore
            # Re-initialize to pick up mocks
            store = VectorStore()
            yield store

@pytest.fixture
def paperless_client():
    """Provides a fresh PaperlessAPIClient instance."""
    from api.paperless_client import PaperlessAPIClient
    client = PaperlessAPIClient()
    yield client
    # The async client must be properly closed after test execution
    # In pytest-asyncio it's handled properly if tests themselves close or if we async teardown
    # For simplicity, tests that open it should close it or we just let it garbage collect in mocks.
